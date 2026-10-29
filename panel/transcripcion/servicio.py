"""Contexto de la transcripción: lo que es común a todos los proveedores.

1. Obtiene el audio con el servicio de audio (y así queda guardado).
2. Prepara el plan: mono, estéreo por canal o estéreo duplicado.
3. Elige la estrategia por sus capacidades, nunca por su nombre: un estéreo
   por canal necesita marcas de tiempo; si la estrategia no las da, el audio
   se transcribe mezclado.
4. Parte el audio si supera lo que acepta el proveedor y une los segmentos.
5. Si una estrategia falla, prueba con la siguiente de la cadena de respaldo
   (patrón Chain of Responsibility).
6. Guarda la transcripción; la primera de cada llamada queda como principal.

La red se usa siempre fuera de una transacción de la base.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from panel.audio.servicio import ServicioAudio
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import (
    TRABAJO_EN_PROCESO,
    TRABAJO_ERROR,
    TRABAJO_HECHO,
    TRABAJO_PENDIENTE,
    TRANSCRIPCION_ELIMINADA,
    TRANSCRIPCION_HECHA,
    Llamada,
    TrabajoTranscripcion,
    TranscripcionGuardada,
)
from panel.transcripcion import preparacion
from panel.transcripcion.base import (
    EstrategiaTranscripcion,
    OpcionesTranscripcion,
    Segmento,
    TranscripcionError,
)

registro = logging.getLogger(__name__)

INTENTOS_POR_TRABAJO = 3
# Un trabajo «en proceso» por más de esto quedó colgado (el proceso se cortó).
TRABAJO_COLGADO = timedelta(hours=1)


class ResultadoTranscripcion(BaseModel):
    transcripcion_id: int | None = None
    proveedor: str | None = None
    error: str | None = None


class VistaTranscripcion(BaseModel):
    id: int
    proveedor: str
    modelo: str
    canales_audio: str
    segmentos: list[Segmento]
    duracion_audio: float | None
    costo_estimado: Decimal | None
    principal: bool
    creado_en: datetime

    @property
    def etiquetas_sin_resolver(self) -> list[str]:
        """Hablantes que el proveedor separó («A», «B») sin saber quién es quién."""
        return sorted(
            {s.etiqueta for s in self.segmentos if s.etiqueta and s.hablante == "desconocido"}
        )


class ResumenCola(BaseModel):
    hechos: int = 0
    reintentos: int = 0
    errores: int = 0


class ResumenRetencionTranscripciones(BaseModel):
    borradas: int = 0


def _ordenar(segmentos: list[Segmento]) -> list[Segmento]:
    # Estable: sin marcas de tiempo se conserva el orden en que llegaron.
    return sorted(segmentos, key=lambda s: (s.inicio is None, s.inicio or 0.0))


def _vista(fila: TranscripcionGuardada) -> VistaTranscripcion:
    return VistaTranscripcion(
        id=fila.id,
        proveedor=fila.proveedor,
        modelo=fila.modelo,
        canales_audio=fila.canales_audio,
        segmentos=[Segmento.model_validate(s) for s in fila.segmentos],
        duracion_audio=fila.duracion_audio,
        costo_estimado=fila.costo_estimado,
        principal=fila.principal,
        creado_en=fila.creado_en,
    )


class ServicioTranscripcion:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        audio: ServicioAudio,
        estrategias: dict[str, EstrategiaTranscripcion],
        cadena: list[str],
        opciones: OpcionesTranscripcion,
        canal_agente: preparacion.CanalAgente = "izquierdo",
        ahora: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        """`estrategias`: las disponibles por nombre. `cadena`: el orden en que
        se prueban (la principal y después las de respaldo)."""
        self._fabrica = fabrica
        self._audio = audio
        self.estrategias = estrategias
        self.cadena = [nombre for nombre in cadena if nombre in estrategias]
        self._opciones = opciones
        self._canal_agente = canal_agente
        self._ahora = ahora

    # --- Transcribir ---------------------------------------------------------

    def transcribir(self, llamada_id: int, proveedor: str | None = None) -> ResultadoTranscripcion:
        cadena = [proveedor] if proveedor else self.cadena
        cadena = [nombre for nombre in cadena if nombre in self.estrategias]
        if not cadena:
            return ResultadoTranscripcion(error="No hay un proveedor de transcripción configurado.")

        audio = self._audio.escuchar(llamada_id)
        if audio.mp3 is None:
            return ResultadoTranscripcion(error=audio.mensaje or "La llamada no tiene audio.")
        if audio.pendiente_de_subir:
            self._audio.subir_pendiente(llamada_id)

        with unidad_de_trabajo(self._fabrica) as sesion:
            nombre = f"{sesion.get(Llamada, llamada_id).id_externo}.mp3"
        plan = preparacion.preparar(audio.mp3, nombre, self._canal_agente)

        errores = []
        for nombre_estrategia in cadena:
            estrategia = self.estrategias[nombre_estrategia]
            plan_usado = plan
            if plan.necesita_marcas and not estrategia.capacidades.marcas_de_tiempo:
                plan_usado = preparacion.como_mono(plan, audio.mp3, nombre)
            try:
                segmentos, costo = self._transcribir_plan(estrategia, plan_usado)
            except TranscripcionError as error:
                registro.warning("Falló %s en la llamada %s: %s", nombre_estrategia, llamada_id, error)
                errores.append(f"{estrategia.titulo}: {error}")
                continue
            transcripcion_id = self._guardar(llamada_id, estrategia, plan_usado, segmentos, costo)
            return ResultadoTranscripcion(transcripcion_id=transcripcion_id, proveedor=nombre_estrategia)
        return ResultadoTranscripcion(error=" · ".join(errores))

    def _transcribir_plan(self, estrategia, plan):
        segmentos: list[Segmento] = []
        costos = []
        tamano = estrategia.capacidades.tamano_max_bytes
        for parte in plan.partes:
            tramos = preparacion.partir(parte, tamano) if tamano else [(0.0, parte)]
            for desde, tramo in tramos:
                resultado = estrategia.transcribir(tramo, self._opciones)
                costos.append(resultado.costo_estimado)
                for segmento in resultado.segmentos:
                    if desde and segmento.inicio is not None:
                        segmento = segmento.model_copy(
                            update={
                                "inicio": segmento.inicio + desde,
                                "fin": None if segmento.fin is None else segmento.fin + desde,
                            }
                        )
                    segmentos.append(segmento)
        costo = None if any(c is None for c in costos) else sum(costos, Decimal("0"))
        return _ordenar(segmentos), costo

    def _guardar(self, llamada_id, estrategia, plan, segmentos, costo) -> int:
        with unidad_de_trabajo(self._fabrica) as sesion:
            hay_principal = sesion.scalar(
                select(func.count())
                .select_from(TranscripcionGuardada)
                .where(TranscripcionGuardada.llamada_id == llamada_id, TranscripcionGuardada.principal)
            )
            fila = TranscripcionGuardada(
                llamada_id=llamada_id,
                proveedor=estrategia.nombre,
                modelo=estrategia.modelo,
                idioma=self._opciones.idioma,
                canales_audio=plan.canales_audio,
                segmentos=[s.model_dump(mode="json") for s in segmentos],
                texto="\n".join(s.texto for s in segmentos),
                duracion_audio=plan.partes[0].duracion_s if plan.partes else None,
                costo_estimado=costo,
                principal=not hay_principal,
            )
            sesion.add(fila)
            sesion.get(Llamada, llamada_id).transcripcion_estado = TRANSCRIPCION_HECHA
            sesion.flush()
            return fila.id

    # --- Leer y corregir -----------------------------------------------------

    def de_llamada(self, llamada_id: int) -> list[VistaTranscripcion]:
        """La principal primero, después de la más nueva a la más vieja."""
        with unidad_de_trabajo(self._fabrica) as sesion:
            filas = sesion.scalars(
                select(TranscripcionGuardada)
                .where(TranscripcionGuardada.llamada_id == llamada_id)
                .order_by(TranscripcionGuardada.principal.desc(), TranscripcionGuardada.creado_en.desc())
            )
            return [_vista(fila) for fila in filas]

    def asignar_hablantes(self, transcripcion_id: int, roles: dict[str, str]) -> None:
        """Dice quién es cada hablante que el proveedor separó: {"A": "agente"}."""
        if any(rol not in ("agente", "cliente", "desconocido") for rol in roles.values()):
            raise ValueError("Cada hablante es agente, cliente o desconocido.")
        with unidad_de_trabajo(self._fabrica) as sesion:
            fila = sesion.get(TranscripcionGuardada, transcripcion_id)
            fila.segmentos = [
                {**s, "hablante": roles.get(s.get("etiqueta"), s["hablante"])}
                if s.get("etiqueta") in roles
                else s
                for s in fila.segmentos
            ]

    def marcar_principal(self, transcripcion_id: int) -> None:
        with unidad_de_trabajo(self._fabrica) as sesion:
            fila = sesion.get(TranscripcionGuardada, transcripcion_id)
            sesion.execute(
                update(TranscripcionGuardada)
                .where(TranscripcionGuardada.llamada_id == fila.llamada_id)
                .values(principal=False)
            )
            sesion.flush()
            fila.principal = True

    # --- Cola ----------------------------------------------------------------

    def encolar(self, llamada_ids: list[int], proveedor: str | None = None) -> int:
        """Pide transcribir esas llamadas. Las que ya tienen un pedido abierto
        no se repiten. Devuelve cuántos pedidos se crearon."""
        with unidad_de_trabajo(self._fabrica) as sesion:
            abiertos = set(
                sesion.scalars(
                    select(TrabajoTranscripcion.llamada_id).where(
                        TrabajoTranscripcion.llamada_id.in_(llamada_ids),
                        TrabajoTranscripcion.estado.in_([TRABAJO_PENDIENTE, TRABAJO_EN_PROCESO]),
                    )
                )
            )
            nuevos = [lid for lid in dict.fromkeys(llamada_ids) if lid not in abiertos]
            sesion.add_all(
                TrabajoTranscripcion(llamada_id=lid, proveedor=proveedor) for lid in nuevos
            )
            return len(nuevos)

    def procesar_cola(self, limite: int) -> ResumenCola:
        """Toma hasta `limite` pedidos pendientes y los transcribe. Varios
        procesos pueden correrla a la vez sin tomar el mismo pedido."""
        with unidad_de_trabajo(self._fabrica) as sesion:
            # Pedidos de un proceso que se cortó a mitad: vuelven a la cola.
            sesion.execute(
                update(TrabajoTranscripcion)
                .where(
                    TrabajoTranscripcion.estado == TRABAJO_EN_PROCESO,
                    TrabajoTranscripcion.actualizado_en < self._ahora() - TRABAJO_COLGADO,
                )
                .values(estado=TRABAJO_PENDIENTE)
            )
            tomados = list(
                sesion.scalars(
                    select(TrabajoTranscripcion)
                    .where(TrabajoTranscripcion.estado == TRABAJO_PENDIENTE)
                    .order_by(TrabajoTranscripcion.creado_en)
                    .limit(limite)
                    .with_for_update(skip_locked=True)
                )
            )
            for trabajo in tomados:
                trabajo.estado = TRABAJO_EN_PROCESO
            pedidos = [(t.id, t.llamada_id, t.proveedor) for t in tomados]

        resumen = ResumenCola()
        for trabajo_id, llamada_id, proveedor in pedidos:
            resultado = self.transcribir(llamada_id, proveedor)
            with unidad_de_trabajo(self._fabrica) as sesion:
                trabajo = sesion.get(TrabajoTranscripcion, trabajo_id)
                trabajo.intentos += 1
                if resultado.error is None:
                    trabajo.estado, trabajo.error = TRABAJO_HECHO, None
                    resumen.hechos += 1
                elif trabajo.intentos < INTENTOS_POR_TRABAJO:
                    trabajo.estado, trabajo.error = TRABAJO_PENDIENTE, resultado.error
                    resumen.reintentos += 1
                else:
                    trabajo.estado, trabajo.error = TRABAJO_ERROR, resultado.error
                    resumen.errores += 1
        return resumen

    def reintentar(self, trabajo_id: int) -> None:
        with unidad_de_trabajo(self._fabrica) as sesion:
            trabajo = sesion.get(TrabajoTranscripcion, trabajo_id)
            if trabajo is not None and trabajo.estado == TRABAJO_ERROR:
                trabajo.estado, trabajo.intentos = TRABAJO_PENDIENTE, 0

    # --- Costos --------------------------------------------------------------

    def costo_de_lote(self, llamada_ids: list[int], proveedor: str | None = None) -> tuple[float, Decimal | None]:
        """Minutos de audio de esas llamadas y lo que costaría transcribirlas."""
        nombre = proveedor or (self.cadena[0] if self.cadena else None)
        with unidad_de_trabajo(self._fabrica) as sesion:
            segundos = sesion.scalar(
                select(func.coalesce(func.sum(Llamada.duracion_s), 0)).where(Llamada.id.in_(llamada_ids))
            )
        estrategia = self.estrategias.get(nombre) if nombre else None
        costo = estrategia.costo_estimado(float(segundos)) if estrategia else None
        return float(segundos) / 60, costo


def borrar_transcripciones_vencidas(
    fabrica: sessionmaker[Session], dias: int, ahora: datetime
) -> ResumenRetencionTranscripciones:
    """Borra las transcripciones de llamadas más viejas que el plazo (3 años por
    defecto). No necesita un proveedor configurado. Las auditorías no se tocan."""
    limite = ahora - timedelta(days=dias)
    with unidad_de_trabajo(fabrica) as sesion:
        vencidas = select(Llamada.id).where(Llamada.inicio < limite)
        borradas = sesion.execute(
            delete(TranscripcionGuardada).where(TranscripcionGuardada.llamada_id.in_(vencidas))
        ).rowcount
        sesion.execute(
            update(Llamada)
            .where(and_(Llamada.inicio < limite, Llamada.transcripcion_estado == TRANSCRIPCION_HECHA))
            .values(transcripcion_estado=TRANSCRIPCION_ELIMINADA)
        )
    if borradas:
        registro.info("Retención de transcripciones: %s borradas", borradas)
    return ResumenRetencionTranscripciones(borradas=borradas)
