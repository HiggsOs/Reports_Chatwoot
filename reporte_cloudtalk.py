"""Armado del reporte de transcripciones a partir de los datos de CloudTalk."""

import csv
import io
import math
import time
from datetime import date, datetime

from cloudtalk import a_fecha_utc, fue_grabada
from reporte import FORMATO_FECHA, TZ
from reporte_ringover import CLIENTE, SIN_TEXTO, formatear_duracion

COLUMNAS = (
    "call_id",
    "agente",
    "fecha",
    "direccion",
    "duracion_total",
    "estado",
    "transcripcion_completa",
)

DIRECCIONES = {"incoming": "entrante", "outgoing": "saliente", "internal": "interna"}

TRANSCRITA = "transcrita"
SIN_TRANSCRIPCION = "sin transcripción"
SIN_GRABACION = "sin grabación"

TIPO_AGENTE = "agent"


def nombre_agente(llamada: dict) -> str:
    """Nombre del agente que atendió la llamada según el historial."""
    agente = llamada.get("Agent") or {}
    completo = (agente.get("fullname") or "").strip()
    if completo:
        return completo

    partes = [
        (agente.get("firstname") or "").strip(),
        (agente.get("lastname") or "").strip(),
    ]
    nombre = " ".join(parte for parte in partes if parte)
    if nombre:
        return nombre

    identificador = agente.get("id") or (llamada.get("Cdr") or {}).get("user_id")
    return f"Agente {identificador}" if identificador else ""


def etiquetas_hablantes(transcripcion: dict, llamada: dict) -> dict[str, str]:
    """`caller1`, `caller2`… → nombre a mostrar en el diálogo.

    A diferencia de Ringover, CloudTalk dice de cada hablante si es agente o
    contacto, así que no hace falta deducirlo por la dirección de la llamada.
    """
    agente = llamada.get("Agent") or {}
    nombre = nombre_agente(llamada)
    etiquetas: dict[str, str] = {}

    for hablante in transcripcion.get("callers") or []:
        local = hablante.get("localIdentifier")
        if not local:
            continue
        if hablante.get("type") != TIPO_AGENTE:
            etiquetas[local] = CLIENTE
        elif str(hablante.get("id")) == str(agente.get("id")) or not hablante.get("id"):
            etiquetas[local] = nombre or "Agente"
        else:
            # Un segundo agente, por ejemplo tras una transferencia.
            etiquetas[local] = f"Agente {hablante['id']}"

    return etiquetas


def texto_transcripcion(transcripcion: dict, llamada: dict) -> str:
    """Une los segmentos en un diálogo con el nombre de cada hablante."""
    etiquetas = etiquetas_hablantes(transcripcion, llamada)
    segmentos = sorted(
        transcripcion.get("segments") or [],
        key=lambda segmento: float(segmento.get("start") or 0),
    )
    lineas = [
        f"[{etiquetas.get(segmento.get('caller'), segmento.get('caller') or '?')}]: {texto}"
        for segmento in segmentos
        if (texto := (segmento.get("text") or "").strip())
    ]
    return "\n".join(lineas)


def construir_fila(llamada: dict, transcripcion: dict | None) -> dict[str, str]:
    cdr = llamada.get("Cdr") or {}
    inicio = a_fecha_utc(cdr.get("started_at"))
    fecha = inicio.astimezone(TZ) if inicio else None
    duracion = cdr.get("talking_time")
    if duracion in (None, ""):
        duracion = cdr.get("billsec")

    if transcripcion is not None:
        estado = TRANSCRITA
        dialogo = texto_transcripcion(transcripcion, llamada) or SIN_TEXTO
    else:
        estado = SIN_TRANSCRIPCION if fue_grabada(llamada) else SIN_GRABACION
        dialogo = ""

    return {
        "call_id": str(cdr.get("id") or ""),
        "agente": nombre_agente(llamada),
        "fecha": fecha.strftime(FORMATO_FECHA) if fecha else "",
        "direccion": DIRECCIONES.get(cdr.get("type") or "", cdr.get("type") or ""),
        "duracion_total": formatear_duracion(duracion),
        "estado": estado,
        "transcripcion_completa": dialogo,
    }


def formatear_espera(segundos: float) -> str:
    """Tiempo restante en palabras, redondeado hacia arriba."""
    if segundos <= 0:
        return ""
    minutos = math.ceil(segundos / 60)
    if minutos <= 1:
        return "menos de 1 min"
    if minutos < 60:
        return f"unos {minutos} min"
    horas, resto = divmod(minutos, 60)
    return f"unas {horas} h {resto} min" if resto else f"unas {horas} h"


def generar_filas(
    cliente, desde: datetime, hasta: datetime, cache=None, al_avanzar=None
) -> list[dict[str, str]]:
    """Trae las llamadas contestadas del rango y la transcripción de cada una.

    CloudTalk no tiene un listado de transcripciones: hay que pedirlas llamada
    por llamada. Las que ya se descargaron se guardan en disco, porque una
    transcripción terminada no cambia y la API limita las peticiones por minuto.

    `al_avanzar(hechas, total, segundos_restantes)` recibe una estimación de lo
    que falta. Las llamadas que ya están en caché no cuentan, porque no hacen
    peticiones; para las demás se usa el ritmo real medido hasta el momento, que
    ya incluye las pausas que haya pedido CloudTalk.
    """
    llamadas = cliente.listar_llamadas(desde, hasta)

    guardadas: dict[str, dict] = {}
    pendientes = 0
    for llamada in llamadas:
        call_id = str((llamada.get("Cdr") or {}).get("id") or "")
        if not call_id or not fue_grabada(llamada):
            continue
        en_cache = cache.leer(call_id) if cache else None
        if en_cache is None:
            pendientes += 1
        else:
            guardadas[call_id] = en_cache

    ritmo_inicial = getattr(cliente, "segundos_por_peticion", 1.0)
    descargadas = 0
    inicio_descargas: float | None = None

    def restante() -> float:
        faltan = pendientes - descargadas
        if descargadas and inicio_descargas is not None:
            ritmo = (time.monotonic() - inicio_descargas) / descargadas
        else:
            ritmo = ritmo_inicial
        return faltan * ritmo

    if al_avanzar and llamadas:
        al_avanzar(0, len(llamadas), restante())

    filas = []
    for numero, llamada in enumerate(llamadas, start=1):
        call_id = str((llamada.get("Cdr") or {}).get("id") or "")
        transcripcion = None

        if call_id and fue_grabada(llamada):
            transcripcion = guardadas.get(call_id)
            if transcripcion is None:
                if inicio_descargas is None:
                    inicio_descargas = time.monotonic()
                transcripcion = cliente.obtener_transcripcion(call_id)
                descargadas += 1
                # Si todavía no hay transcripción no se guarda nada: puede
                # aparecer más tarde.
                if transcripcion is not None and cache:
                    cache.guardar(call_id, transcripcion)

        filas.append(construir_fila(llamada, transcripcion))
        if al_avanzar:
            al_avanzar(numero, len(llamadas), restante())

    return sorted(filas, key=lambda fila: fila["fecha"])


def escribir_csv(filas: list[dict[str, str]]) -> bytes:
    """CSV con BOM para que Excel en Windows respete los acentos."""
    memoria = io.StringIO()
    escritor = csv.DictWriter(memoria, fieldnames=list(COLUMNAS), lineterminator="\r\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return memoria.getvalue().encode("utf-8-sig")


def nombre_archivo(desde: date, hasta: date) -> str:
    return f"reporte-cloudtalk-{desde:%Y-%m-%d}-a-{hasta:%Y-%m-%d}.csv"
