"""Inicio: pendientes, números de la semana y estado de la sincronización."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.contenedor import Contenedor
from api.dependencias import contenedor, sesion
from panel.composicion import sincronizadores
from panel.servicios import consultas
from panel.sync.sincronizadores import ejecutar_ciclo
from panel.transcripcion import consultas as consultas_transcripcion

router = APIRouter(prefix="/api", tags=["inicio"])
DIAS = 7


class PuntoSync(BaseModel):
    fuente: str
    hasta: datetime | None
    ultimo_intento: datetime | None
    ultimo_exito: datetime | None
    ultimo_error: str | None
    resumen: dict | None


class EstadoConfig(BaseModel):
    cloudtalk: bool
    chatwoot: bool
    almacen: str
    transcripcion: bool
    tope_mensual_usd: float | None
    aviso_porcentaje: int
    retencion_audio_dias: int
    intervalo_minutos: int
    error_ajustes: str | None
    ajustes_ilegibles: list[str]
    # Para «Abrir en Chatwoot»: la URL de una conversación con {id} en lugar del número.
    chatwoot_conversacion: str | None


class Inicio(BaseModel):
    ahora: datetime
    semana: consultas.Resumen
    semana_anterior: consultas.Resumen
    sincronizacion: list[PuntoSync]
    cola: dict[str, int]
    audios_por_vencer: int
    gasto_mes_usd: float
    config: EstadoConfig


def estado_config(c: Contenedor) -> EstadoConfig:
    cfg = c.cfg
    return EstadoConfig(
        cloudtalk=cfg.cloudtalk_configurado,
        chatwoot=cfg.chatwoot_configurado,
        almacen=cfg.almacen_tipo,
        transcripcion=c.transcripcion is not None,
        tope_mensual_usd=float(cfg.transcripcion_tope_mensual_usd) if cfg.transcripcion_tope_mensual_usd else None,
        aviso_porcentaje=cfg.transcripcion_aviso_porcentaje,
        retencion_audio_dias=cfg.audio_retencion_dias,
        intervalo_minutos=cfg.sync_intervalo_minutos,
        error_ajustes=c.error_ajustes,
        ajustes_ilegibles=c.lectura.ilegibles,
        chatwoot_conversacion=(
            f"{cfg.base_url}/app/accounts/{cfg.account_id}/conversations/{{id}}" if cfg.chatwoot_configurado else None
        ),
    )


@router.get("/estado", response_model=EstadoConfig)
def ver_estado(c: Contenedor = Depends(contenedor)) -> EstadoConfig:
    """Lo que la barra lateral y los avisos necesitan saber en cada pantalla."""
    return estado_config(c)


@router.get("/inicio", response_model=Inicio)
def ver_inicio(c: Contenedor = Depends(contenedor), s: Session = Depends(sesion)) -> Inicio:
    ahora = datetime.now(timezone.utc)
    desde = ahora - timedelta(days=DIAS)
    return Inicio(
        ahora=ahora,
        semana=consultas.resumen(s, desde, ahora),
        semana_anterior=consultas.resumen(s, desde - timedelta(days=DIAS), desde),
        sincronizacion=[PuntoSync.model_validate(p, from_attributes=True)
                        for p in consultas.estado_sincronizacion(s)],
        cola=consultas_transcripcion.estado_cola(s),
        audios_por_vencer=consultas.audios_por_vencer(s, ahora, c.cfg.audio_retencion_dias),
        gasto_mes_usd=float(consultas_transcripcion.gasto_del_mes(s, ahora)),
        config=estado_config(c),
    )


class ResultadoCiclo(BaseModel):
    fuente: str
    error: str | None = None
    resumen: dict = {}


@router.post("/sincronizar", response_model=list[ResultadoCiclo])
def sincronizar(c: Contenedor = Depends(contenedor)) -> list[ResultadoCiclo]:
    resultados = ejecutar_ciclo(c.fabrica, sincronizadores(c.fabrica, c.cfg))
    if resultados is None:
        raise HTTPException(409, "Ya hay una sincronización en curso. Vuelva a mirar en unos minutos.")
    return [ResultadoCiclo(fuente=r.fuente, error=r.error, resumen=r.resumen or {}) for r in resultados]
