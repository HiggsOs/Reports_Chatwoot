"""Guardado y asignación de llamadas y conversaciones."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from panel.asignacion.servicio import (
    ZONA_OPERACION_POR_DEFECTO,
    AsignacionResuelta,
    ServicioAsignacion,
)
from panel.db.modelos import (
    ASIGNACION_AUTOMATICA,
    ASIGNACION_MANUAL,
    Cliente,
    Conversacion,
    Cuenta,
    Llamada,
)
from panel.db.repositorios.personas import RepositorioPersonas
from panel.fuentes.interacciones import (
    ConversacionExterna,
    LlamadaExterna,
    asesor_con_mas_mensajes,
    es_abandonada,
)
from panel.servicios.cuentas import ServicioCuentas
from panel.telefonos import normalizar
from reporte import INDETERMINADO, detectar_cierre, detectar_direccion

MOTIVO_SIN_USUARIO = "La conversación no tiene usuario asignado en Chatwoot"
MOTIVO_SIN_USUARIO_NI_MENSAJES = (
    "La conversación no tiene usuario asignado en Chatwoot ni mensajes de asesores"
)
MOTIVO_POR_MENSAJES = "Sin usuario en Chatwoot: el asesor que más mensajes envió"
MOTIVO_FINALIZACION = (
    "Finalización de la conversación {anterior}: sin respuesta y con un solo "
    "mensaje del cliente, toma su asesor"
)
MOTIVO_MANUAL = "Asignada a mano"
PLAZO_FINALIZACION_POR_DEFECTO = timedelta(days=7)
SIN_ASIGNAR = "Sin asignar"

Tipo = Literal["llamada", "conversacion"]
MODELOS = {"llamada": Llamada, "conversacion": Conversacion}


class ResumenGuardado(BaseModel):
    nuevas: int = 0
    actualizadas: int = 0
    sin_asignar: int = 0


class ResumenReasignacion(BaseModel):
    revisadas: int = 0
    cambiaron: int = 0
    # Etiqueta de la persona (o «Sin asignar») → cantidad, tras reasignar.
    por_persona: dict[str, int] = {}


class ServicioInteracciones:
    def __init__(
        self,
        sesion: Session,
        zona=ZONA_OPERACION_POR_DEFECTO,
        plazo_finalizacion: timedelta = PLAZO_FINALIZACION_POR_DEFECTO,
    ) -> None:
        self._sesion = sesion
        self._plazo_finalizacion = plazo_finalizacion
        self.asignacion = ServicioAsignacion(sesion, zona)
        self._cuentas = ServicioCuentas(sesion, self.asignacion)
        self._personas = RepositorioPersonas(sesion)

    # --- Guardado ------------------------------------------------------------

    def guardar_llamadas(self, llamadas: list[LlamadaExterna]) -> ResumenGuardado:
        resumen = ResumenGuardado()
        existentes = self._existentes(Llamada, [ll.id_externo for ll in llamadas])
        for externa in llamadas:
            cuenta = self._cuentas.asegurar("cloudtalk", externa.agente)
            llamada = existentes.get(externa.id_externo)
            nueva = llamada is None
            if nueva:
                llamada = Llamada(id_externo=externa.id_externo, asignacion=ASIGNACION_AUTOMATICA)
            llamada.cuenta_id = cuenta.id
            llamada.inicio = externa.inicio
            llamada.duracion_s = externa.duracion_s
            llamada.direccion = externa.direccion
            llamada.grabada = externa.grabada
            llamada.enlace_plataforma = externa.enlace_plataforma
            llamada.datos_origen = externa.datos_origen
            llamada.cliente_id = self._cliente(externa.telefono_cliente, externa.nombre_cliente)
            self._asignar_automatica(llamada)
            # Se agrega a la sesión recién completa: las consultas de arriba
            # harían un autoflush de una fila a medias.
            if nueva:
                self._sesion.add(llamada)
            resumen.nuevas += nueva
            resumen.actualizadas += not nueva
            resumen.sin_asignar += llamada.persona_id is None
        self._sesion.flush()
        return resumen

    def ultima_actividad_guardada(
        self, ids_externos: list[str]
    ) -> dict[str, tuple[datetime | None, bool]]:
        """id externo → (última actividad guardada, si tiene los mensajes
        guardados). Para saber qué conversaciones necesitan pedir sus mensajes."""
        return {
            id_externo: (ultima, tiene_mensajes)
            for id_externo, ultima, tiene_mensajes in self._sesion.execute(
                select(
                    Conversacion.id_externo,
                    Conversacion.ultima_actividad,
                    Conversacion.mensajes.is_not(None),
                ).where(Conversacion.id_externo.in_(ids_externos))
            )
        }

    def guardar_conversaciones(
        self, conversaciones: list[tuple[ConversacionExterna, list[dict] | None]]
    ) -> ResumenGuardado:
        """`mensajes` en None: la conversación no cambió y conserva su dirección
        y su cierre.

        Se guardan de la más vieja a la más nueva, para que una abandonada
        encuentre a la conversación anterior aunque llegue en el mismo lote."""
        conversaciones = sorted(conversaciones, key=lambda par: par[0].inicio)
        resumen = ResumenGuardado()
        existentes = self._existentes(
            Conversacion, [externa.id_externo for externa, _ in conversaciones]
        )
        for externa, mensajes in conversaciones:
            conversacion = existentes.get(externa.id_externo)
            nueva = conversacion is None
            if nueva:
                conversacion = Conversacion(
                    id_externo=externa.id_externo,
                    asignacion=ASIGNACION_AUTOMATICA,
                    direccion=INDETERMINADO,
                    cierre_aproximado=False,
                )
            if mensajes is not None:
                conversacion.mensajes = mensajes
                conversacion.direccion = detectar_direccion(mensajes)
                cierre, aproximado = detectar_cierre(externa.datos_origen, mensajes)
                conversacion.cierre = cierre
                conversacion.cierre_aproximado = aproximado
            conversacion.inicio = externa.inicio
            conversacion.ultima_actividad = externa.ultima_actividad
            conversacion.canal = externa.canal
            conversacion.estado = externa.estado
            conversacion.etiquetas = externa.etiquetas
            conversacion.datos_origen = externa.datos_origen
            conversacion.cliente_id = self._cliente(
                externa.telefono_cliente, externa.nombre_cliente
            )
            self._asignar_cuenta(conversacion, externa)
            self._asignar_automatica(conversacion)
            if nueva:
                self._sesion.add(conversacion)
            resumen.nuevas += nueva
            resumen.actualizadas += not nueva
            resumen.sin_asignar += conversacion.persona_id is None
        self._sesion.flush()
        # Una conversación que cambió de asesor se lo pasa a sus finalizaciones.
        self._actualizar_finalizaciones([c.id for c in existentes.values()])
        return resumen

    def _asignar_cuenta(self, conversacion: Conversacion, externa: ConversacionExterna) -> None:
        """La cuenta es el usuario asignado en Chatwoot. Sin él, la del asesor
        que más mensajes envió (con los mensajes guardados si no llegaron
        nuevos); si ningún asesor escribió, ninguna."""
        conversacion.cuenta_por_mensajes = False
        conversacion.continua_de_id = None
        if externa.usuario is not None:
            conversacion.cuenta_id = self._cuentas.asegurar("chatwoot", externa.usuario).id
            return
        mensajes = conversacion.mensajes or []
        asesor = asesor_con_mas_mensajes(mensajes)
        if asesor is not None:
            conversacion.cuenta_id = self._cuentas.asegurar("chatwoot", asesor.cuenta).id
            conversacion.cuenta_por_mensajes = True
            return
        anterior = self._conversacion_anterior(conversacion) if es_abandonada(mensajes) else None
        if anterior is not None:
            conversacion.cuenta_id = anterior.cuenta_id
            conversacion.continua_de_id = anterior.id
            return
        conversacion.cuenta_id = None

    def _conversacion_anterior(self, conversacion: Conversacion) -> Conversacion | None:
        """La última conversación propia del mismo cliente, si su última
        actividad fue hasta el plazo de finalización antes de esta."""
        if conversacion.cliente_id is None:
            return None
        consulta = (
            select(Conversacion)
            .where(
                Conversacion.cliente_id == conversacion.cliente_id,
                Conversacion.continua_de_id.is_(None),
                Conversacion.inicio < conversacion.inicio,
                func.coalesce(Conversacion.ultima_actividad, Conversacion.inicio)
                >= conversacion.inicio - self._plazo_finalizacion,
            )
            .order_by(Conversacion.inicio.desc())
            .limit(1)
        )
        if conversacion.id is not None:
            consulta = consulta.where(Conversacion.id != conversacion.id)
        return self._sesion.scalar(consulta)

    def _actualizar_finalizaciones(self, conversacion_ids: list[int]) -> None:
        """Las finalizaciones automáticas toman el asesor actual de la
        conversación que finalizan."""
        if not conversacion_ids:
            return
        for finalizacion in self._sesion.scalars(
            select(Conversacion).where(
                Conversacion.continua_de_id.in_(conversacion_ids),
                Conversacion.asignacion == ASIGNACION_AUTOMATICA,
            )
        ):
            finalizacion.cuenta_id = self._sesion.get(
                Conversacion, finalizacion.continua_de_id
            ).cuenta_id
            self._asignar_automatica(finalizacion)
        self._sesion.flush()

    def _existentes(self, modelo, ids_externos: list[str]) -> dict:
        if not ids_externos:
            return {}
        return {
            fila.id_externo: fila
            for fila in self._sesion.scalars(
                select(modelo).where(modelo.id_externo.in_(ids_externos))
            )
        }

    def _cliente(self, telefono: str | None, nombre: str | None) -> int | None:
        normalizado = normalizar(telefono)
        if normalizado is None:
            return None
        cliente = self._sesion.scalar(select(Cliente).where(Cliente.telefono == normalizado.valor))
        if cliente is None:
            cliente = Cliente(
                telefono=normalizado.valor,
                telefono_original=normalizado.original,
                nombre=nombre,
                revisar=normalizado.revisar,
            )
            self._sesion.add(cliente)
            self._sesion.flush()
        elif nombre and not cliente.nombre:
            cliente.nombre = nombre
        return cliente.id

    # --- Asignación -----------------------------------------------------------

    def _resolver(self, interaccion) -> AsignacionResuelta:
        if getattr(interaccion, "continua_de_id", None) is not None:
            anterior = self._sesion.get(Conversacion, interaccion.continua_de_id)
            return AsignacionResuelta(
                persona_id=anterior.persona_id,
                motivo=MOTIVO_FINALIZACION.format(anterior=anterior.id_externo),
                regla_id=anterior.regla_id,
            )
        if interaccion.cuenta_id is None:
            motivo = MOTIVO_SIN_USUARIO
            if isinstance(interaccion, Conversacion) and interaccion.mensajes is not None:
                motivo = MOTIVO_SIN_USUARIO_NI_MENSAJES
            return AsignacionResuelta(persona_id=None, motivo=motivo, regla_id=None)
        resuelta = self.asignacion.resolver(interaccion.cuenta_id, interaccion.inicio)
        por_mensajes = getattr(interaccion, "cuenta_por_mensajes", False)
        if resuelta.persona_id is None and isinstance(interaccion, Conversacion):
            # Una cuenta de Chatwoot es una persona: si su regla no da a nadie
            # (no tiene, o el asesor se cargó después), vale el asesor con su correo.
            persona = self._persona_por_correo(interaccion.cuenta_id)
            if persona is not None:
                origen = MOTIVO_POR_MENSAJES if por_mensajes else "Usuario asignado en Chatwoot"
                return AsignacionResuelta(
                    persona_id=persona.id,
                    motivo=f"{origen}: {persona.etiqueta} (por el correo de su cuenta de Chatwoot)",
                    regla_id=None,
                )
        if por_mensajes:
            resuelta.motivo = f"{MOTIVO_POR_MENSAJES} · {resuelta.motivo}"
        return resuelta

    def _persona_por_correo(self, cuenta_id: int):
        cuenta = self._sesion.get(Cuenta, cuenta_id)
        if cuenta is None or not cuenta.correo:
            return None
        return self._personas.activa_por_correo(cuenta.correo)

    def _asignar_automatica(self, interaccion) -> bool:
        """Recalcula la asignación salvo que sea manual. Dice si cambió la persona."""
        if interaccion.asignacion == ASIGNACION_MANUAL:
            return False
        resuelta = self._resolver(interaccion)
        cambio = interaccion.persona_id != resuelta.persona_id
        interaccion.asignacion = ASIGNACION_AUTOMATICA
        interaccion.persona_id = resuelta.persona_id
        interaccion.regla_id = resuelta.regla_id
        interaccion.motivo_asignacion = resuelta.motivo
        return cambio

    def asignar_manual(self, tipo: Tipo, interaccion_id: int, persona_id: int | None) -> None:
        """Fija la persona a mano (o la deja sin asignar). La sincronización y
        los cambios de regla ya no la tocan."""
        interaccion = self._obtener(tipo, interaccion_id)
        if persona_id is not None:
            persona = self._personas.por_ids({persona_id}).get(persona_id)
            if persona is None or not persona.activa:
                raise ValueError("Elija un asesor activo.")
        interaccion.asignacion = ASIGNACION_MANUAL
        interaccion.persona_id = persona_id
        interaccion.regla_id = None
        interaccion.motivo_asignacion = MOTIVO_MANUAL
        self._sesion.flush()
        if tipo == "conversacion":
            self._actualizar_finalizaciones([interaccion.id])

    def volver_a_automatica(self, tipo: Tipo, interaccion_id: int) -> None:
        interaccion = self._obtener(tipo, interaccion_id)
        interaccion.asignacion = ASIGNACION_AUTOMATICA
        self._asignar_automatica(interaccion)
        self._sesion.flush()
        if tipo == "conversacion":
            self._actualizar_finalizaciones([interaccion.id])

    def _obtener(self, tipo: Tipo, interaccion_id: int):
        interaccion = self._sesion.get(MODELOS[tipo], interaccion_id)
        if interaccion is None:
            raise LookupError(f"No existe la {tipo} {interaccion_id}.")
        return interaccion

    def reasignar_cuenta(self, cuenta_id: int, desde: datetime) -> ResumenReasignacion:
        """Recalcula las interacciones automáticas de la cuenta desde esa fecha,
        por ejemplo después de guardar una regla nueva."""
        self.asignacion.olvidar(cuenta_id)
        resumen = ResumenReasignacion()
        conteo: dict[int | None, int] = {}
        for modelo in MODELOS.values():
            consulta = select(modelo).where(
                modelo.cuenta_id == cuenta_id,
                modelo.inicio >= desde,
                modelo.asignacion == ASIGNACION_AUTOMATICA,
            ).order_by(modelo.inicio)
            for interaccion in self._sesion.scalars(consulta):
                cambio = self._asignar_automatica(interaccion)
                # Una finalización sigue a su conversación, pero no se cuenta aparte.
                if getattr(interaccion, "continua_de_id", None) is not None:
                    continue
                resumen.revisadas += 1
                resumen.cambiaron += cambio
                conteo[interaccion.persona_id] = conteo.get(interaccion.persona_id, 0) + 1
        self._sesion.flush()

        nombres = {
            pid: p.etiqueta
            for pid, p in self._personas.por_ids({pid for pid in conteo if pid}).items()
        }
        resumen.por_persona = {
            (nombres.get(pid, "?") if pid is not None else SIN_ASIGNAR): cantidad
            for pid, cantidad in sorted(conteo.items(), key=lambda par: -par[1])
        }
        return resumen

    def revisar_sin_asignar(self) -> ResumenReasignacion:
        """Vuelve a mirar los chats sin asesor (los automáticos): la cuenta sale
        de quién más mensajes envió, con los mensajes guardados, y después la
        persona de su regla o de su correo. Sirve tras cargar asesores o
        reglas nuevas, porque la sincronización solo revisa lo que cambió."""
        resumen = ResumenReasignacion()
        conteo: dict[int | None, int] = {}
        pendientes = self._sesion.scalars(
            select(Conversacion).where(
                Conversacion.persona_id.is_(None),
                Conversacion.asignacion == ASIGNACION_AUTOMATICA,
                Conversacion.continua_de_id.is_(None),
            ).order_by(Conversacion.inicio)
        )
        cambiadas = []
        for conversacion in pendientes:
            if conversacion.cuenta_id is None or conversacion.cuenta_por_mensajes:
                asesor = asesor_con_mas_mensajes(conversacion.mensajes or [])
                if asesor is not None:
                    conversacion.cuenta_id = self._cuentas.asegurar("chatwoot", asesor.cuenta).id
                    conversacion.cuenta_por_mensajes = True
            cambio = self._asignar_automatica(conversacion)
            resumen.revisadas += 1
            resumen.cambiaron += cambio
            if cambio:
                cambiadas.append(conversacion.id)
                conteo[conversacion.persona_id] = conteo.get(conversacion.persona_id, 0) + 1
        self._sesion.flush()
        self._actualizar_finalizaciones(cambiadas)
        nombres = {pid: p.etiqueta for pid, p in self._personas.por_ids({pid for pid in conteo if pid}).items()}
        resumen.por_persona = {
            (nombres.get(pid, "?") if pid is not None else SIN_ASIGNAR): cantidad
            for pid, cantidad in sorted(conteo.items(), key=lambda par: -par[1])
        }
        return resumen

    def simular_regla(
        self, cuenta_id: int, estrategia: str, parametros, vigente_desde: datetime,
        corregir_posteriores: bool = False,
    ) -> ResumenReasignacion:
        """Qué pasaría con las interacciones si se guardara la regla, sin
        guardar nada. Lanza ReglaInvalida igual que crear_regla."""
        punto = self._sesion.begin_nested()
        try:
            self.asignacion.crear_regla(cuenta_id, estrategia, parametros, vigente_desde, corregir_posteriores)
            return self.reasignar_cuenta(cuenta_id, vigente_desde)
        finally:
            punto.rollback()
            self.asignacion.olvidar(cuenta_id)

    def simular_reasignacion(self, cuenta_id: int, desde: datetime) -> ResumenReasignacion:
        """Qué cambiaría al volver a calcular la asignación, sin guardar nada."""
        punto = self._sesion.begin_nested()
        try:
            return self.reasignar_cuenta(cuenta_id, desde)
        finally:
            punto.rollback()
            self.asignacion.olvidar(cuenta_id)
