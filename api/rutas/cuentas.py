"""Cuentas de CloudTalk y Chatwoot y sus reglas de asignación."""

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.contenedor import Contenedor
from api.dependencias import contenedor, sesion
from chatwoot import ChatwootError, ClienteChatwoot
from cloudtalk import ClienteCloudTalk, CloudTalkError
from panel.asignacion import registro
from panel.asignacion.servicio import DESDE_SIEMPRE, ReglaInvalida, ServicioAsignacion, ocupacion_semanal
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.cuentas import RepositorioCuentas, RepositorioReglas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.fuentes.cuentas import cuentas_de_chatwoot, cuentas_de_cloudtalk
from panel.servicios.cuentas import ServicioCuentas
from panel.servicios.interacciones import ResumenReasignacion, ServicioInteracciones

router = APIRouter(prefix="/api", tags=["cuentas"])
NOMBRES = {"cloudtalk": "CloudTalk", "chatwoot": "Chatwoot"}


class Estrategia(BaseModel):
    nombre: str
    titulo: str
    descripcion: str


@router.get("/estrategias", response_model=list[Estrategia])
def estrategias(_c: Contenedor = Depends(contenedor)) -> list[Estrategia]:
    return [Estrategia(nombre=e.nombre, titulo=e.titulo, descripcion=e.descripcion) for e in registro.disponibles()]


class FilaCuenta(BaseModel):
    id: int
    plataforma: str
    nombre: str
    correo: str | None
    estrategia: str | None  # título; None: sin regla
    detalle: list[str]
    aviso: str
    vigente_desde: datetime | None


@router.get("/cuentas", response_model=list[FilaCuenta])
def listar(s: Session = Depends(sesion)) -> list[FilaCuenta]:
    servicio, reglas, ahora = ServicioAsignacion(s), RepositorioReglas(s), datetime.now(timezone.utc)
    filas = []
    for cuenta in RepositorioCuentas(s).listar():
        regla = reglas.vigente(cuenta.id, ahora)
        if regla is None:
            filas.append(FilaCuenta(id=cuenta.id, plataforma=cuenta.plataforma, nombre=cuenta.nombre,
                                    correo=cuenta.correo, estrategia=None, detalle=[],
                                    aviso="Sin regla: sus interacciones quedan sin asignar", vigente_desde=None))
            continue
        inactivas = servicio.personas_inactivas(regla)
        filas.append(FilaCuenta(
            id=cuenta.id, plataforma=cuenta.plataforma, nombre=cuenta.nombre, correo=cuenta.correo,
            estrategia=registro.obtener(regla.estrategia).titulo, detalle=servicio.describir(regla),
            aviso=f"Nombra asesores inactivos: {', '.join(inactivas)}" if inactivas else "",
            vigente_desde=None if regla.vigente_desde == DESDE_SIEMPRE else regla.vigente_desde,
        ))
    # Primero las que no tienen regla: son las que dejan llamadas sin asignar.
    return sorted(filas, key=lambda f: (f.estrategia is not None, f.plataforma, f.nombre.lower()))


class ReglaHistorica(BaseModel):
    estrategia: str
    desde: str
    hasta: str
    detalle: list[str]


class DetalleCuenta(BaseModel):
    id: int
    nombre: str
    plataforma: str
    estrategia: str | None  # nombre interno de la regla vigente
    parametros: dict[str, Any] | None
    horario: list[list[str | None]]  # 7 días × 24 horas: quién atiende, o None
    historial: list[ReglaHistorica]
    ultima_estrategia: str | None
    ultimos_parametros: dict[str, Any] | None


@router.get("/cuentas/{cuenta_id}", response_model=DetalleCuenta)
def detalle(cuenta_id: int, s: Session = Depends(sesion)) -> DetalleCuenta:
    cuenta = RepositorioCuentas(s).obtener(cuenta_id)
    if cuenta is None:
        raise HTTPException(404, "La cuenta no existe.")
    reglas, servicio = RepositorioReglas(s), ServicioAsignacion(s)
    vigente = reglas.vigente(cuenta_id, datetime.now(timezone.utc))
    horario: list[list[str | None]] = [[None] * 24 for _ in range(7)]
    if vigente is not None:
        estrategia = registro.obtener(vigente.estrategia)
        parametros = estrategia.Parametros.model_validate(vigente.parametros)
        nombres = {pid: p.etiqueta for pid, p in RepositorioPersonas(s).por_ids(estrategia.personas(parametros)).items()}
        for celda in ocupacion_semanal(estrategia, parametros, paso_minutos=60):
            pid = celda.resultado.persona_id
            horario[celda.dia][celda.hora.hour] = nombres.get(pid, "?") if pid is not None else None
    historial = []
    for regla in reglas.historial(cuenta_id):
        corregida = regla.vigente_hasta == regla.vigente_desde
        historial.append(ReglaHistorica(
            estrategia=registro.obtener(regla.estrategia).titulo,
            desde="desde siempre" if regla.vigente_desde == DESDE_SIEMPRE else servicio.formatear_fecha(regla.vigente_desde),
            hasta="corregida, nunca rigió" if corregida else (
                servicio.formatear_fecha(regla.vigente_hasta) if regla.vigente_hasta else "vigente"),
            detalle=servicio.describir(regla),
        ))
    ultima = reglas.ultima(cuenta_id)
    return DetalleCuenta(
        id=cuenta.id, nombre=cuenta.nombre, plataforma=cuenta.plataforma,
        estrategia=vigente.estrategia if vigente else None,
        parametros=dict(vigente.parametros) if vigente else None,
        horario=horario, historial=historial,
        ultima_estrategia=ultima.estrategia if ultima else None,
        ultimos_parametros=dict(ultima.parametros) if ultima else None,
    )


class NuevaRegla(BaseModel):
    estrategia: str
    parametros: dict[str, Any]
    desde_siempre: bool = False
    desde: date | None = None
    previa: bool = True  # True: solo simula


@router.post("/cuentas/{cuenta_id}/reglas", response_model=ResumenReasignacion)
def nueva_regla(cuenta_id: int, datos: NuevaRegla, s: Session = Depends(sesion)) -> ResumenReasignacion:
    if RepositorioCuentas(s).obtener(cuenta_id) is None:
        raise HTTPException(404, "La cuenta no existe.")
    servicio = ServicioInteracciones(s)
    if datos.desde_siempre:
        vigente_desde = DESDE_SIEMPRE
    elif datos.desde is not None:
        vigente_desde = servicio.asignacion.inicio_del_dia(datos.desde)
    else:
        raise HTTPException(422, "Indique desde cuándo vale la regla.")
    try:
        if datos.previa:
            return servicio.simular_regla(cuenta_id, datos.estrategia, datos.parametros, vigente_desde)
        servicio.asignacion.crear_regla(cuenta_id, datos.estrategia, datos.parametros, vigente_desde)
        return servicio.reasignar_cuenta(cuenta_id, vigente_desde)
    except ReglaInvalida as error:
        raise HTTPException(422, " ".join(error.errores)) from error


class Actualizacion(BaseModel):
    mensajes: list[str]
    errores: list[str]


@router.post("/cuentas/actualizar", response_model=Actualizacion)
def actualizar(c: Contenedor = Depends(contenedor)) -> Actualizacion:
    cfg = c.cfg
    fuentes = []
    if cfg.cloudtalk_configurado:
        fuentes.append(("cloudtalk", lambda: cuentas_de_cloudtalk(ClienteCloudTalk(
            cfg.cloudtalk_key_id, cfg.cloudtalk_key_secret, cfg.cloudtalk_base_url, intentos_limite=1
        ).listar_agentes())))
    if cfg.chatwoot_configurado:
        fuentes.append(("chatwoot", lambda: cuentas_de_chatwoot(
            ClienteChatwoot(cfg.base_url, cfg.account_id, cfg.api_token).listar_agentes())))
    mensajes, errores = [], []
    if not fuentes:
        errores.append("No hay ninguna plataforma conectada. Configure CloudTalk o Chatwoot en General.")
    for plataforma, traer in fuentes:
        try:
            externas = traer()
        except (ChatwootError, CloudTalkError) as error:
            errores.append(f"{NOMBRES[plataforma]}: {error}")
            continue
        with unidad_de_trabajo(c.fabrica) as s:
            r = ServicioCuentas(s).actualizar(plataforma, externas)
        mensajes.append(
            f"{NOMBRES[plataforma]}: {len(externas)} cuentas ({r.nuevas} nuevas, {r.actualizadas} con cambios, "
            f"{r.reactivadas} reactivadas, {r.desactivadas} desactivadas)."
        )
    return Actualizacion(mensajes=mensajes, errores=errores)
