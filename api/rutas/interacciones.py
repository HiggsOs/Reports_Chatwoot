"""Llamadas, conversaciones, Sin asignar e Historial del cliente."""

from datetime import date, datetime, time, timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.contenedor import Contenedor
from api.dependencias import contenedor, sesion
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.modelos import Conversacion, Llamada
from panel.db.repositorios.cuentas import RepositorioCuentas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import PersonaResumida
from panel.servicios import clientes, consultas
from panel.servicios.interacciones import ServicioInteracciones

router = APIRouter(prefix="/api", tags=["interacciones"])

Tipo = Literal["llamada", "conversacion"]
LISTAR = {"llamada": consultas.listar_llamadas, "conversacion": consultas.listar_conversaciones}
MODELOS = {"llamada": Llamada, "conversacion": Conversacion}
PLATAFORMA = {"llamada": "cloudtalk", "conversacion": "chatwoot"}
COLUMNAS_CSV = {
    "llamada": {
        "id_externo": "Id CloudTalk", "inicio": "Fecha", "asesor": "Asesor", "asignacion": "Asignación",
        "motivo": "Motivo", "cliente": "Cliente", "telefono": "Teléfono", "direccion": "Dirección",
        "duracion_s": "Duración (s)", "audio_estado": "Audio", "transcripcion_estado": "Transcripción",
        "cuenta": "Cuenta", "area": "Área", "transcripcion_texto": "Texto de la transcripción",
    },
    "conversacion": {
        "id_externo": "Id Chatwoot", "inicio": "Fecha", "asesor": "Asesor", "asignacion": "Asignación",
        "motivo": "Motivo", "cliente": "Cliente", "telefono": "Teléfono", "canal": "Canal",
        "estado": "Estado", "etiquetas": "Etiquetas", "horas_resolucion": "Horas de resolución",
        "cierre": "Cierre", "cuenta": "Cuenta", "area": "Área",
    },
}


def inicio_del_dia(dia: date) -> datetime:
    return datetime.combine(dia, time.min, tzinfo=ZONA_OPERACION_POR_DEFECTO)


class Opcion(BaseModel):
    id: int
    nombre: str


class Catalogos(BaseModel):
    personas: list[PersonaResumida]
    cuentas: dict[str, list[Opcion]]  # plataforma → cuentas


@router.get("/catalogos", response_model=Catalogos)
def catalogos(s: Session = Depends(sesion)) -> Catalogos:
    cuentas: dict[str, list[Opcion]] = {"cloudtalk": [], "chatwoot": []}
    for cuenta in RepositorioCuentas(s).listar(incluir_inactivas=True):
        cuentas.setdefault(cuenta.plataforma, []).append(Opcion(id=cuenta.id, nombre=cuenta.nombre))
    return Catalogos(personas=RepositorioPersonas(s).listar(), cuentas=cuentas)


def _filtros(
    desde: date, hasta: date, personas: list[int], cuentas: list[int], cliente: str, sin_asignar: bool
) -> consultas.Filtros:
    if desde > hasta:
        raise HTTPException(422, "La fecha inicial no puede ser posterior a la final.")
    return consultas.Filtros(
        desde=inicio_del_dia(desde),
        hasta=inicio_del_dia(hasta + timedelta(days=1)),
        persona_ids=personas,
        cuenta_ids=cuentas,
        solo_sin_asignar=sin_asignar,
        cliente=cliente,
    )


class Listado(BaseModel):
    filas: list[consultas.FilaLlamada] | list[consultas.FilaConversacion]
    limite: int
    recortado: bool


def _parametros(
    desde: date = Query(...),
    hasta: date = Query(...),
    personas: list[int] = Query(default=[]),
    cuentas: list[int] = Query(default=[]),
    cliente: str = "",
    sin_asignar: bool = False,
) -> consultas.Filtros:
    return _filtros(desde, hasta, personas, cuentas, cliente, sin_asignar)


@router.get("/interacciones/{tipo}", response_model=Listado)
def listar(tipo: Tipo, filtros: consultas.Filtros = Depends(_parametros), s: Session = Depends(sesion)) -> Listado:
    filas = LISTAR[tipo](s, filtros)
    return Listado(filas=filas, limite=consultas.LIMITE_FILAS, recortado=len(filas) >= consultas.LIMITE_FILAS)


@router.get("/interacciones/{tipo}/csv")
def descargar_csv(tipo: Tipo, filtros: consultas.Filtros = Depends(_parametros), s: Session = Depends(sesion)):
    filas = LISTAR[tipo](s, filtros)
    if tipo == "llamada":
        filas = consultas.con_transcripciones(s, filas)
    nombre = f"{'llamadas' if tipo == 'llamada' else 'conversaciones'}_{filtros.desde:%Y-%m-%d}.csv"
    return Response(
        consultas.a_csv(filas, COLUMNAS_CSV[tipo]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


class Asignacion(BaseModel):
    persona_id: int | None


def _existe(s: Session, tipo: Tipo, interaccion_id: int) -> None:
    if s.get(MODELOS[tipo], interaccion_id) is None:
        raise HTTPException(404, "No existe.")


@router.put("/interacciones/{tipo}/{interaccion_id}/asignacion", status_code=204)
def asignar(tipo: Tipo, interaccion_id: int, datos: Asignacion, s: Session = Depends(sesion)) -> None:
    _existe(s, tipo, interaccion_id)
    ServicioInteracciones(s).asignar_manual(tipo, interaccion_id, datos.persona_id)


@router.delete("/interacciones/{tipo}/{interaccion_id}/asignacion", status_code=204)
def volver_a_automatica(tipo: Tipo, interaccion_id: int, s: Session = Depends(sesion)) -> None:
    _existe(s, tipo, interaccion_id)
    ServicioInteracciones(s).volver_a_automatica(tipo, interaccion_id)


class AsignacionEnBloque(BaseModel):
    tipo: Tipo
    ids: list[int]
    persona_id: int


class ResultadoBloque(BaseModel):
    asignadas: int


@router.post("/sin-asignar/asignar", response_model=ResultadoBloque)
def asignar_en_bloque(datos: AsignacionEnBloque, s: Session = Depends(sesion)) -> ResultadoBloque:
    servicio = ServicioInteracciones(s)
    for interaccion_id in dict.fromkeys(datos.ids):
        _existe(s, datos.tipo, interaccion_id)
        servicio.asignar_manual(datos.tipo, interaccion_id, datos.persona_id)
    return ResultadoBloque(asignadas=len(set(datos.ids)))


@router.get("/conversaciones/{conversacion_id}/mensajes", response_model=list[clientes.Mensaje] | None)
def mensajes(conversacion_id: int, s: Session = Depends(sesion)) -> list[clientes.Mensaje] | None:
    """None: los mensajes todavía no están guardados."""
    _existe(s, "conversacion", conversacion_id)
    return clientes.mensajes_de_conversacion(s, conversacion_id)


@router.get("/llamadas/{llamada_id}/audio")
def audio(llamada_id: int, tareas: BackgroundTasks, c: Contenedor = Depends(contenedor)):
    """El MP3 de la llamada. Escucharla la guarda en el almacén (90 días)."""
    if c.audio is None:
        raise HTTPException(409, "Para escuchar las llamadas hay que configurar CloudTalk en General.")
    resultado = c.audio.escuchar(llamada_id)
    if resultado.mp3 is None:
        raise HTTPException(404, resultado.mensaje or "La llamada no tiene audio.")
    if resultado.pendiente_de_subir:
        # Después de responder: la subida no demora la escucha.
        tareas.add_task(c.audio.subir_pendiente, llamada_id)
    return Response(
        resultado.mp3,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=3600", "X-Panel-Mensaje": quote(resultado.mensaje)},
    )


@router.get("/clientes", response_model=list[clientes.ResumenCliente])
def buscar_clientes(q: str = "", revisar: bool = False, s: Session = Depends(sesion)):
    return clientes.buscar(s, q, revisar)


@router.get("/clientes/{cliente_id}", response_model=clientes.Historial)
def historial(cliente_id: int, s: Session = Depends(sesion)) -> clientes.Historial:
    resultado = clientes.historial(s, cliente_id)
    if resultado is None:
        raise HTTPException(404, "El cliente ya no existe.")
    return resultado
