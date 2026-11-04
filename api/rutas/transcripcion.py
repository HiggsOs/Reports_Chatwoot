"""Transcripción: la de cada llamada, la cola, el gasto y la configuración."""

import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.contenedor import Contenedor
from api.dependencias import contenedor, sesion
from config import ConfigError, ModeloTranscripcion
from panel.ajustes import enmascarar, guardar_validado, origenes
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.modelos import Llamada
from panel.transcripcion import consultas, registro
from panel.transcripcion.base import TranscripcionError
from panel.transcripcion.estrategias.openai import MODELO_POR_DEFECTO
from panel.transcripcion.servicio import ServicioTranscripcion, VistaTranscripcion

router = APIRouter(prefix="/api", tags=["transcripción"])


def _servicio(c: Contenedor) -> ServicioTranscripcion:
    if c.transcripcion is None:
        raise HTTPException(
            409, "La transcripción no está configurada: elija el modelo principal y cargue la "
                 "clave del proveedor en Transcripción › Configuración."
        )
    return c.transcripcion


def que_devuelve(proveedor: str, modelo: str) -> str:
    capacidades = registro.modelos_conocidos(proveedor).get(modelo)
    if capacidades is None:
        return "solo texto"
    if capacidades.diarizacion:
        return "separa hablantes, con tiempos"
    return "con tiempos" if capacidades.marcas_de_tiempo else "solo texto"


class OpcionModelo(BaseModel):
    clave: str
    titulo: str
    devuelve: str
    costo_usd: float | None


class TranscripcionesLlamada(BaseModel):
    configurada: bool
    versiones: list[VistaTranscripcion]
    opciones: list[OpcionModelo]
    pedido: consultas.PedidoLlamada | None = None


def _opciones(servicio: ServicioTranscripcion, llamada_ids: list[int]) -> list[OpcionModelo]:
    nombres = list(servicio.cadena) + [n for n in servicio.estrategias if n not in servicio.cadena and n != "falsa"]
    opciones = []
    for nombre in nombres:
        estrategia = servicio.estrategias[nombre]
        _, costo = servicio.costo_de_lote(llamada_ids, nombre)
        opciones.append(OpcionModelo(
            clave=nombre, titulo=registro.titulo(nombre),
            devuelve=que_devuelve(estrategia.nombre, estrategia.modelo),
            costo_usd=float(costo) if costo is not None else None,
        ))
    return opciones


@router.get("/llamadas/{llamada_id}/transcripciones", response_model=TranscripcionesLlamada)
def de_llamada(
    llamada_id: int, c: Contenedor = Depends(contenedor), s: Session = Depends(sesion)
) -> TranscripcionesLlamada:
    pedido = consultas.pedido_de_llamada(s, llamada_id)
    if c.transcripcion is None:
        return TranscripcionesLlamada(configurada=False, versiones=[], opciones=[], pedido=pedido)
    servicio = c.transcripcion
    return TranscripcionesLlamada(
        configurada=True, versiones=servicio.de_llamada(llamada_id), opciones=_opciones(servicio, [llamada_id]),
        pedido=pedido,
    )


class Pedido(BaseModel):
    proveedor: str | None = None


def _procesar_pedido(servicio: ServicioTranscripcion, trabajo_id: int) -> None:
    servicio.procesar_cola(1, trabajo_ids=[trabajo_id])


@router.post("/llamadas/{llamada_id}/transcripciones", response_model=consultas.PedidoLlamada, status_code=202)
def transcribir(
    llamada_id: int, pedido: Pedido, tareas: BackgroundTasks,
    c: Contenedor = Depends(contenedor), s: Session = Depends(sesion),
) -> consultas.PedidoLlamada:
    """Pone la llamada en la cola y la transcribe enseguida, en segundo plano.
    Si falla, queda en la cola con su motivo y la sincronización la reintenta."""
    servicio = _servicio(c)
    llamada = s.get(Llamada, llamada_id)
    if llamada is None:
        raise HTTPException(404, "La llamada no existe.")
    if not llamada.grabada:
        raise HTTPException(409, "La llamada no se grabó.")
    trabajo_id = servicio.pedir(llamada_id, pedido.proveedor)
    tareas.add_task(_procesar_pedido, servicio, trabajo_id)
    return consultas.pedido_de_llamada(s, llamada_id)


@router.post("/transcripciones/{transcripcion_id}/principal", status_code=204)
def marcar_principal(transcripcion_id: int, c: Contenedor = Depends(contenedor)) -> None:
    _servicio(c).marcar_principal(transcripcion_id)


class Hablantes(BaseModel):
    agente: str  # la etiqueta del hablante que es el agente («A»)
    etiquetas: list[str]


@router.post("/transcripciones/{transcripcion_id}/hablantes", status_code=204)
def asignar_hablantes(transcripcion_id: int, datos: Hablantes, c: Contenedor = Depends(contenedor)) -> None:
    roles = {e: ("agente" if e == datos.agente else "cliente") for e in datos.etiquetas}
    _servicio(c).asignar_hablantes(transcripcion_id, roles)


class Lote(BaseModel):
    ids: list[int]
    confirmado: bool = False


class CostoLote(BaseModel):
    llamadas: int
    minutos: float
    costo_usd: float | None
    requiere_confirmacion: bool
    umbral_usd: float | None
    modelo: str | None


def _pendientes(s: Session, ids: list[int]) -> list[int]:
    """Las que tienen grabación y no están transcritas."""
    return [
        llamada.id for llamada in (s.get(Llamada, i) for i in dict.fromkeys(ids))
        if llamada is not None and llamada.grabada and not llamada.transcripcion_estado
        and llamada.audio_estado not in ("sin_grabacion", "vencido")
    ]


def _costo_lote(c: Contenedor, s: Session, ids: list[int]) -> tuple[list[int], CostoLote]:
    servicio = _servicio(c)
    pendientes = _pendientes(s, ids)
    minutos, costo = servicio.costo_de_lote(pendientes) if pendientes else (0.0, Decimal(0))
    umbral = c.cfg.transcripcion_confirmar_lote_usd
    return pendientes, CostoLote(
        llamadas=len(pendientes), minutos=minutos,
        costo_usd=float(costo) if costo is not None else None,
        requiere_confirmacion=bool(umbral is not None and costo is not None and costo > umbral),
        umbral_usd=float(umbral) if umbral is not None else None,
        modelo=registro.titulo(servicio.cadena[0]) if servicio.cadena else None,
    )


@router.post("/transcripcion/lote/costo", response_model=CostoLote)
def costo_lote(lote: Lote, c: Contenedor = Depends(contenedor), s: Session = Depends(sesion)) -> CostoLote:
    return _costo_lote(c, s, lote.ids)[1]


class Encolado(BaseModel):
    encoladas: int
    costo_usd: float | None


@router.post("/transcripcion/lote", response_model=Encolado)
def encolar_lote(lote: Lote, c: Contenedor = Depends(contenedor), s: Session = Depends(sesion)) -> Encolado:
    pendientes, costo = _costo_lote(c, s, lote.ids)
    if costo.requiere_confirmacion and not lote.confirmado:
        raise HTTPException(409, f"El lote supera el límite de {costo.umbral_usd} USD: confirme el gasto.")
    return Encolado(encoladas=c.transcripcion.encolar(pendientes), costo_usd=costo.costo_usd)


class Resumen(BaseModel):
    configurada: bool
    cola: dict[str, int]
    gasto_mes_usd: float
    tope_mensual_usd: float | None
    aviso_porcentaje: int
    por_ciclo: int
    intervalo_minutos: int
    auto_min_segundos: int
    errores: list[consultas.TrabajoConError]
    abiertos: list[consultas.TrabajoEnCola]
    costo_reintento_usd: float | None


@router.get("/transcripcion/resumen", response_model=Resumen)
def resumen(c: Contenedor = Depends(contenedor), s: Session = Depends(sesion)) -> Resumen:
    cfg = c.cfg
    errores = consultas.trabajos_con_error(s)
    costo = None
    if c.transcripcion is not None and errores:
        costo = c.transcripcion.costo_de_lote([e.llamada_id for e in errores])[1]
    return Resumen(
        configurada=c.transcripcion is not None,
        cola=consultas.estado_cola(s),
        gasto_mes_usd=float(consultas.gasto_del_mes(s, datetime.now(ZONA_OPERACION_POR_DEFECTO))),
        tope_mensual_usd=float(cfg.transcripcion_tope_mensual_usd) if cfg.transcripcion_tope_mensual_usd else None,
        aviso_porcentaje=cfg.transcripcion_aviso_porcentaje,
        por_ciclo=cfg.transcripcion_por_ciclo,
        intervalo_minutos=cfg.sync_intervalo_minutos,
        auto_min_segundos=cfg.transcripcion_auto_min_segundos,
        errores=errores,
        abiertos=consultas.trabajos_abiertos(s),
        costo_reintento_usd=float(costo) if costo is not None else None,
    )


@router.post("/transcripcion/reintentar", response_model=Encolado)
def reintentar(c: Contenedor = Depends(contenedor), s: Session = Depends(sesion)) -> Encolado:
    servicio = _servicio(c)
    errores = consultas.trabajos_con_error(s)
    for error in errores:
        servicio.reintentar(error.id)
    return Encolado(encoladas=len(errores), costo_usd=None)


class FilaGasto(BaseModel):
    proveedor: str
    modelo: str
    titulo: str
    minutos_panel: float
    usd_estimado: float | None
    minutos_cobrados: float | None
    usd_cobrados: float | None
    precio_configurado: float | None
    precio_real: float | None
    diferencia: float | None
    desviado: bool


def _f(valor) -> float | None:
    return None if valor is None else float(valor)


@router.get("/transcripcion/gasto", response_model=list[FilaGasto])
def gasto(mes: date, c: Contenedor = Depends(contenedor), s: Session = Depends(sesion)) -> list[FilaGasto]:
    precios = {(m.proveedor, m.modelo): m.precio_minuto for m in c.cfg.transcripcion_modelos}
    return [
        FilaGasto(
            proveedor=f.proveedor, modelo=f.modelo, titulo=registro.titulo(f"{f.proveedor}:{f.modelo}"),
            minutos_panel=f.minutos_panel, usd_estimado=_f(f.usd_estimado),
            minutos_cobrados=_f(f.minutos_cobrados), usd_cobrados=_f(f.usd_cobrados),
            precio_configurado=_f(f.precio_configurado), precio_real=_f(f.precio_real),
            diferencia=_f(f.diferencia), desviado=f.desviado,
        )
        for f in consultas.precio_real(s, mes, precios)
    ]


class Cobro(BaseModel):
    mes: date
    proveedor: str
    modelo: str
    minutos: Decimal
    usd: Decimal


@router.put("/transcripcion/cobros", status_code=204)
def guardar_cobro(cobro: Cobro, s: Session = Depends(sesion)) -> None:
    if cobro.minutos < 0 or cobro.usd < 0:
        raise HTTPException(422, "Los minutos y el importe no pueden ser negativos.")
    consultas.guardar_cobro(s, cobro.mes, cobro.proveedor, cobro.modelo, cobro.minutos, cobro.usd)


@router.get("/transcripcion/comparables", response_model=list[consultas.LlamadaComparable])
def comparables(s: Session = Depends(sesion)):
    return consultas.llamadas_comparables(s)


# --- Configuración ------------------------------------------------------------


class Proveedor(BaseModel):
    nombre: str
    titulo: str
    variable_clave: str | None
    clave_mascara: str  # vacío: sin clave
    origen_clave: str | None  # «panel», «entorno» o nada
    modelos_conocidos: dict[str, str]  # modelo → qué devuelve


class ConfiguracionTranscripcion(BaseModel):
    proveedores: list[Proveedor]
    modelos: list[ModeloTranscripcion]
    principal: str | None
    respaldo: list[str]
    idioma: str
    vocabulario: list[str]
    canal_agente: str
    auto_min_segundos: int
    tope_mensual_usd: float | None
    aviso_porcentaje: int
    confirmar_lote_usd: float | None


def _modelos_iniciales(c: Contenedor) -> list[ModeloTranscripcion]:
    cfg = c.cfg
    if cfg.transcripcion_modelos:
        return list(cfg.transcripcion_modelos)
    efectivo = {**c.entorno, **c.lectura.valores}
    actual = (efectivo.get("OPENAI_MODELO_TRANSCRIPCION") or MODELO_POR_DEFECTO).strip()
    precio = (efectivo.get("OPENAI_PRECIO_MINUTO") or "").strip().replace(",", ".") or None
    modelos = [ModeloTranscripcion(proveedor="openai", modelo=actual, precio_minuto=precio)]
    modelos += [ModeloTranscripcion(proveedor="openai", modelo=m, activo=False)
                for m in registro.modelos_conocidos("openai") if m != actual]
    return modelos


@router.get("/transcripcion/configuracion", response_model=ConfiguracionTranscripcion)
def ver_configuracion(c: Contenedor = Depends(contenedor)) -> ConfiguracionTranscripcion:
    cfg = c.cfg
    efectivo = {**c.entorno, **c.lectura.valores}
    origen = origenes(c.entorno, c.lectura)
    proveedores = []
    for nombre in registro.nombres():
        if nombre == "falsa":
            continue
        variable = registro.variable_clave(nombre)
        proveedores.append(Proveedor(
            nombre=nombre, titulo=registro.titulo(nombre), variable_clave=variable,
            clave_mascara=enmascarar((efectivo.get(variable) or "").strip()) if variable else "",
            origen_clave=origen.get(variable) if variable else None,
            modelos_conocidos={m: que_devuelve(nombre, m) for m in registro.modelos_conocidos(nombre)},
        ))
    modelos = _modelos_iniciales(c)
    activos = {m.clave: True for m in modelos if m.activo}
    return ConfiguracionTranscripcion(
        proveedores=proveedores,
        modelos=modelos,
        principal=registro.resolver(cfg.transcripcion_proveedor, activos),
        respaldo=[r for r in (registro.resolver(n, activos) for n in cfg.transcripcion_respaldo) if r],
        idioma=cfg.transcripcion_idioma,
        vocabulario=list(cfg.transcripcion_vocabulario),
        canal_agente=cfg.cloudtalk_canal_agente,
        auto_min_segundos=cfg.transcripcion_auto_min_segundos,
        tope_mensual_usd=_f(cfg.transcripcion_tope_mensual_usd),
        aviso_porcentaje=cfg.transcripcion_aviso_porcentaje,
        confirmar_lote_usd=_f(cfg.transcripcion_confirmar_lote_usd),
    )


class CambiosTranscripcion(BaseModel):
    modelos: list[ModeloTranscripcion]
    principal: str | None
    respaldo: list[str] = []
    idioma: str = "es"
    vocabulario: list[str] = []
    canal_agente: str = "izquierdo"
    auto_min_segundos: int = 0
    tope_mensual_usd: float | None = None
    aviso_porcentaje: int = 80
    confirmar_lote_usd: float | None = None


def _importe(valor: float | None) -> str:
    return f"{valor:g}" if valor else ""


def guardar(c: Contenedor, cambios: dict[str, str | None]) -> None:
    try:
        guardar_validado(c.fabrica, c.entorno, c.lectura, cambios)
    except ConfigError as error:
        raise HTTPException(422, str(error)) from error
    c.recargar()


@router.put("/transcripcion/configuracion", status_code=204)
def guardar_configuracion(datos: CambiosTranscripcion, c: Contenedor = Depends(contenedor)) -> None:
    claves = [m.clave for m in datos.modelos]
    if len(claves) != len(set(claves)):
        raise HTTPException(422, "Hay un modelo repetido.")
    activos = {m.clave for m in datos.modelos if m.activo}
    if datos.principal and datos.principal not in activos:
        raise HTTPException(422, "El modelo principal tiene que estar activo.")
    guardar(c, {
        "TRANSCRIPCION_MODELOS": json.dumps([m.model_dump(mode="json") for m in datos.modelos], ensure_ascii=False),
        "TRANSCRIPCION_PROVEEDOR": datos.principal or "",
        "TRANSCRIPCION_RESPALDO": ",".join(r for r in datos.respaldo if r in activos and r != datos.principal),
        "TRANSCRIPCION_IDIOMA": datos.idioma.strip(),
        "TRANSCRIPCION_VOCABULARIO": ",".join(p.strip() for p in datos.vocabulario if p.strip()),
        "CLOUDTALK_CANAL_AGENTE": datos.canal_agente,
        "TRANSCRIPCION_AUTO_MIN_SEGUNDOS": str(datos.auto_min_segundos),
        "TRANSCRIPCION_TOPE_MENSUAL_USD": _importe(datos.tope_mensual_usd),
        "TRANSCRIPCION_AVISO_PORCENTAJE": str(datos.aviso_porcentaje),
        "TRANSCRIPCION_CONFIRMAR_LOTE_USD": _importe(datos.confirmar_lote_usd),
    })


class Clave(BaseModel):
    clave: str | None = None  # vacío o None: se quita del panel


def _variable(proveedor: str) -> str:
    variable = registro.variable_clave(proveedor)
    if variable is None:
        raise HTTPException(404, "Ese proveedor no usa clave de API.")
    return variable


@router.put("/transcripcion/claves/{proveedor}", status_code=204)
def guardar_clave(proveedor: str, datos: Clave, c: Contenedor = Depends(contenedor)) -> None:
    guardar(c, {_variable(proveedor): (datos.clave or "").strip() or None})


class Prueba(BaseModel):
    ok: bool
    mensaje: str


@router.post("/transcripcion/claves/{proveedor}/probar", response_model=Prueba)
def probar_clave(proveedor: str, datos: Clave, c: Contenedor = Depends(contenedor)) -> Prueba:
    variable = _variable(proveedor)
    valores = {**c.entorno, **c.lectura.valores}
    if datos.clave:
        valores[variable] = datos.clave.strip()
    try:
        return Prueba(ok=True, mensaje=registro.probar_clave(proveedor, valores))
    except TranscripcionError as error:
        return Prueba(ok=False, mensaje=str(error))
