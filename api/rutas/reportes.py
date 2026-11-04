"""Reporte de Chatwoot consultado en el momento, para descargar las conversaciones.

Es el mismo reporte de la versión Streamlit (`reporte.py`): una fila por
conversación del rango, con el asesor asignado en Chatwoot y su área. Puede
tardar minutos (pide los mensajes de cada conversación), así que corre en un
hilo: el frontend lo inicia, consulta el avance y al terminar descarga el CSV.
Los reportes viven en memoria; se guardan los últimos `REPORTES_GUARDADOS`.
"""

import logging
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from api.contenedor import Contenedor
from api.dependencias import contenedor
from chatwoot import CacheMensajes, ChatwootError, ClienteChatwoot
from config import ruta_cache
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.personas import RepositorioPersonas
from panel.exportar import TIPO_XLSX, a_excel
from reporte import COLUMNAS, SIN_MAPEAR, TZ, escribir_csv, generar_filas, nombre_archivo

router = APIRouter(prefix="/api/reportes", tags=["reportes"])

registro = logging.getLogger(__name__)

REPORTES_GUARDADOS = 5


@dataclass
class Trabajo:
    id: str
    desde: date
    hasta: date
    estado: str = "en_curso"  # en_curso | listo | error
    hechas: int = 0
    total: int = 0
    error: str | None = None
    filas: list[dict[str, str]] = field(default_factory=list)


class Reportes:
    """Los reportes de Chatwoot en curso y los últimos terminados."""

    def __init__(self) -> None:
        self._trabajos: OrderedDict[str, Trabajo] = OrderedDict()
        self._candado = threading.Lock()

    def nuevo(self, desde: date, hasta: date) -> Trabajo:
        trabajo = Trabajo(id=secrets.token_urlsafe(9), desde=desde, hasta=hasta)
        with self._candado:
            self._trabajos[trabajo.id] = trabajo
            while len(self._trabajos) > REPORTES_GUARDADOS:
                self._trabajos.popitem(last=False)
        return trabajo

    def obtener(self, trabajo_id: str) -> Trabajo:
        with self._candado:
            trabajo = self._trabajos.get(trabajo_id)
        if trabajo is None:
            raise HTTPException(404, "El reporte ya no está disponible. Genérelo de nuevo.")
        return trabajo


def _reportes(request: Request) -> Reportes:
    return request.app.state.reportes


def correr(trabajo: Trabajo, cliente, mapeo: dict[str, str], cache) -> None:
    def avanzar(hechas: int, total: int) -> None:
        trabajo.hechas, trabajo.total = hechas, total

    try:
        trabajo.filas = generar_filas(
            cliente,
            datetime.combine(trabajo.desde, time.min, tzinfo=TZ),
            datetime.combine(trabajo.hasta, time.max, tzinfo=TZ),
            mapeo,
            cache=cache,
            al_avanzar=avanzar,
        )
        trabajo.estado = "listo"
    except ChatwootError as error:
        trabajo.error, trabajo.estado = f"No se pudo consultar Chatwoot. {error}", "error"
    except Exception:  # noqa: BLE001 — el hilo no debe morir en silencio
        registro.exception("Falló el reporte de Chatwoot")
        trabajo.error, trabajo.estado = "Falló el reporte; el detalle está en el log del servicio.", "error"


class Rango(BaseModel):
    desde: date
    hasta: date


class Iniciado(BaseModel):
    id: str


class Estado(BaseModel):
    id: str
    desde: date
    hasta: date
    estado: str
    hechas: int
    total: int
    error: str | None
    sin_mapear: list[str]
    filas: list[dict[str, str]] | None


@router.post("/chatwoot", response_model=Iniciado)
def iniciar(datos: Rango, request: Request, c: Contenedor = Depends(contenedor)) -> Iniciado:
    cfg = c.cfg
    if not cfg.chatwoot_configurado:
        raise HTTPException(409, "Chatwoot no está conectado. Cargue la URL, la cuenta y el token en General.")
    if datos.desde > datos.hasta:
        raise HTTPException(422, "La fecha inicial no puede ser posterior a la final.")
    with unidad_de_trabajo(c.fabrica) as s:
        mapeo = RepositorioPersonas(s).mapa_areas()
    trabajo = _reportes(request).nuevo(datos.desde, datos.hasta)
    cliente = ClienteChatwoot(cfg.base_url, cfg.account_id, cfg.api_token)
    threading.Thread(
        target=correr,
        args=(trabajo, cliente, mapeo, CacheMensajes(ruta_cache(cfg))),
        name=f"reporte-chatwoot-{trabajo.id}",
        daemon=True,
    ).start()
    return Iniciado(id=trabajo.id)


@router.get("/chatwoot/{trabajo_id}", response_model=Estado)
def ver(trabajo_id: str, request: Request, _c: Contenedor = Depends(contenedor)) -> Estado:
    trabajo = _reportes(request).obtener(trabajo_id)
    listo = trabajo.estado == "listo"
    return Estado(
        id=trabajo.id,
        desde=trabajo.desde,
        hasta=trabajo.hasta,
        estado=trabajo.estado,
        hechas=trabajo.hechas,
        total=trabajo.total,
        error=trabajo.error,
        sin_mapear=sorted({f["email_asesor"] for f in trabajo.filas if f["area"] == SIN_MAPEAR}) if listo else [],
        filas=trabajo.filas if listo else None,
    )


@router.get("/chatwoot/{trabajo_id}/{formato}")
def descargar(
    trabajo_id: str, formato: Literal["csv", "xlsx"], request: Request, _c: Contenedor = Depends(contenedor)
) -> Response:
    """El reporte en CSV o en Excel (.xlsx)."""
    trabajo = _reportes(request).obtener(trabajo_id)
    if trabajo.estado != "listo":
        raise HTTPException(409, "El reporte todavía no terminó.")
    nombre = nombre_archivo(trabajo.desde, trabajo.hasta)
    if formato == "xlsx":
        contenido = a_excel(COLUMNAS, ([f.get(c, "") for c in COLUMNAS] for f in trabajo.filas), "Reporte Chatwoot")
        nombre, tipo_mime = nombre.removesuffix(".csv") + ".xlsx", TIPO_XLSX
    else:
        contenido, tipo_mime = escribir_csv(trabajo.filas), "text/csv; charset=utf-8"
    return Response(contenido, media_type=tipo_mime, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})

