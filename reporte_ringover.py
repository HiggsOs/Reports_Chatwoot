"""Armado del reporte de transcripciones a partir de los datos de Ringover."""

import csv
import io
from datetime import date, datetime

from reporte import FORMATO_FECHA, TZ
from ringover import RingoverAuthError

COLUMNAS = (
    "call_id",
    "agente",
    "fecha",
    "duracion_total",
    "estado",
    "transcripcion_completa",
)

# En las intervenciones, `channelId` distingue a quien emite la llamada (1) de
# quien la recibe (0). Quién de los dos es el agente depende de la dirección de
# la llamada, que se consulta en el registro de llamadas.
CANAL_QUIEN_EMITE = 1
CANAL_QUIEN_RECIBE = 0

SALIENTE = "out"

CLIENTE = "Cliente"
SIN_TEXTO = "(sin texto detectado)"


def nombre_agente(transcripcion: dict) -> str:
    """Nombre del usuario de Ringover dueño de la llamada."""
    usuario = transcripcion.get("user") or {}
    concatenado = (usuario.get("concat_name") or "").strip()
    if concatenado:
        return concatenado

    partes = [
        (usuario.get("firstname") or "").strip(),
        (usuario.get("lastname") or "").strip(),
    ]
    nombre = " ".join(parte for parte in partes if parte)
    if nombre:
        return nombre

    identificador = usuario.get("user_id") or transcripcion.get("user_id")
    return f"Usuario {identificador}" if identificador else ""


def a_fecha_local(texto: str | None) -> datetime | None:
    """Convierte la fecha ISO en UTC que devuelve la API a la hora local."""
    if not texto:
        return None
    try:
        momento = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return momento.astimezone(TZ)


def formatear_duracion(duracion) -> str:
    """La API devuelve los segundos como número o como texto, según el caso."""
    if duracion is None or duracion == "":
        return ""
    try:
        return f"{float(duracion):.2f}s"
    except (TypeError, ValueError):
        return str(duracion)


def canal_del_agente(direccion: str | None) -> int:
    """En una llamada saliente el agente es quien emite; en una entrante, quien
    recibe. Sin dirección conocida se asume entrante, que es lo habitual."""
    if (direccion or "").strip().lower() == SALIENTE:
        return CANAL_QUIEN_EMITE
    return CANAL_QUIEN_RECIBE


def etiqueta_hablante(canal, agente: str, canal_agente: int) -> str:
    return agente if canal == canal_agente else CLIENTE


def texto_transcripcion(
    intervenciones: list[dict], agente: str, canal_agente: int = CANAL_QUIEN_RECIBE
) -> str:
    """Une las intervenciones en un diálogo con el nombre de cada hablante."""
    lineas = [
        f"[{etiqueta_hablante(intervencion.get('channelId'), agente, canal_agente)}]: {texto}"
        for intervencion in intervenciones
        if (texto := (intervencion.get("text") or "").strip())
    ]
    return "\n".join(lineas)


def construir_fila(
    transcripcion: dict, direcciones: dict[str, str] | None = None
) -> dict[str, str]:
    datos = transcripcion.get("transcription_data") or {}
    agente = nombre_agente(transcripcion)
    fecha = a_fecha_local(transcripcion.get("creation_date"))
    call_id = str(transcripcion.get("call_id") or "")
    canal_agente = canal_del_agente((direcciones or {}).get(call_id))
    dialogo = texto_transcripcion(datos.get("speeches") or [], agente, canal_agente)

    return {
        "call_id": call_id,
        "agente": agente,
        "fecha": fecha.strftime(FORMATO_FECHA) if fecha else "",
        "duracion_total": formatear_duracion(datos.get("duration")),
        "estado": transcripcion.get("transcription_status") or "",
        "transcripcion_completa": dialogo or SIN_TEXTO,
    }


AVISO_SIN_DIRECCIONES = (
    "No se pudo consultar el registro de llamadas: el token necesita el permiso "
    "«Calls Read». Las transcripciones salen igual, pero en las llamadas "
    "salientes el agente y el cliente pueden quedar intercambiados."
)


def generar_filas(
    cliente, desde: datetime, hasta: datetime, al_avanzar=None, al_advertir=None
) -> list[dict[str, str]]:
    """Trae las transcripciones del rango y arma una fila por cada llamada.

    La dirección de cada llamada sale del registro de llamadas, que es lo único
    que permite saber cuál de los dos canales es el agente. Si ese registro no
    está disponible se avisa y se sigue suponiendo llamadas entrantes.
    """
    try:
        direcciones = cliente.listar_direcciones(desde, hasta)
    except RingoverAuthError:
        direcciones = {}
        if al_advertir:
            al_advertir(AVISO_SIN_DIRECCIONES)

    transcripciones = cliente.listar_transcripciones(desde, hasta, al_avanzar=al_avanzar)
    filas = [construir_fila(t, direcciones) for t in transcripciones]
    return sorted(filas, key=lambda fila: fila["fecha"])


def escribir_csv(filas: list[dict[str, str]]) -> bytes:
    """CSV con BOM para que Excel en Windows respete los acentos."""
    memoria = io.StringIO()
    escritor = csv.DictWriter(memoria, fieldnames=list(COLUMNAS), lineterminator="\r\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return memoria.getvalue().encode("utf-8-sig")


def nombre_archivo(desde: date, hasta: date) -> str:
    return f"reporte-transcripciones-{desde:%Y-%m-%d}-a-{hasta:%Y-%m-%d}.csv"
