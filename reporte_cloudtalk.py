"""Armado del reporte de transcripciones a partir de los datos de CloudTalk."""

import csv
import io
import math
import re
import time
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class Filtros:
    """Qué llamadas entran al reporte. Un conjunto vacío no filtra nada.

    Todo se evalúa sobre el historial de llamadas, antes de pedir las
    transcripciones: cada llamada descartada es una petición menos.
    """

    agentes: frozenset[str] = field(default_factory=frozenset)  # ids de agente
    grupos: frozenset[str] = field(default_factory=frozenset)  # nombres de grupo
    numeros: frozenset[str] = field(default_factory=frozenset)  # ids de número
    direcciones: frozenset[str] = field(default_factory=frozenset)  # incoming…
    duracion_minima: int = 0  # segundos de conversación
    contacto: str = ""  # nombre, empresa o teléfono del cliente
    solo_con_transcripcion: bool = False


def _digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def _segundos(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def _coincide_contacto(llamada: dict, busqueda: str) -> bool:
    contacto = llamada.get("Contact") or {}
    busqueda = busqueda.strip().lower()
    textos = [contacto.get("name"), contacto.get("company")]
    if any(busqueda in str(texto or "").lower() for texto in textos):
        return True

    # Por teléfono se compara solo por dígitos, para que «+57 300…» y
    # «57300…» sean lo mismo.
    digitos = _digitos(busqueda)
    if len(digitos) < 4:
        return False
    telefonos = [(llamada.get("Cdr") or {}).get("public_external")]
    telefonos += contacto.get("contact_numbers") or []
    return any(digitos in _digitos(telefono) for telefono in telefonos)


def cumple_filtros(llamada: dict, filtros: Filtros) -> bool:
    cdr = llamada.get("Cdr") or {}
    agente = llamada.get("Agent") or {}

    if filtros.agentes:
        id_agente = str(agente.get("id") or cdr.get("user_id") or "")
        if id_agente not in filtros.agentes:
            return False

    if filtros.grupos:
        # El historial trae los grupos del agente por nombre.
        grupos_agente = {str(g).strip().lower() for g in agente.get("groups") or []}
        if not grupos_agente & {g.strip().lower() for g in filtros.grupos}:
            return False

    if filtros.numeros:
        id_numero = str((llamada.get("CallNumber") or {}).get("id") or "")
        if id_numero not in filtros.numeros:
            return False

    if filtros.direcciones and (cdr.get("type") or "") not in filtros.direcciones:
        return False

    if filtros.duracion_minima:
        duracion = cdr.get("talking_time")
        if duracion in (None, ""):
            duracion = cdr.get("billsec")
        if _segundos(duracion) < filtros.duracion_minima:
            return False

    if filtros.contacto.strip() and not _coincide_contacto(llamada, filtros.contacto):
        return False

    if filtros.solo_con_transcripcion and not fue_grabada(llamada):
        return False

    return True


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
    cliente,
    desde: datetime,
    hasta: datetime,
    cache=None,
    al_avanzar=None,
    filtros: Filtros | None = None,
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
    filtros = filtros or Filtros()
    llamadas = [
        llamada
        for llamada in cliente.listar_llamadas(desde, hasta)
        if cumple_filtros(llamada, filtros)
    ]

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

        if transcripcion is not None or not filtros.solo_con_transcripcion:
            filas.append(construir_fila(llamada, transcripcion))
        if al_avanzar:
            al_avanzar(numero, len(llamadas), restante())

    return sorted(filas, key=lambda fila: fila["fecha"])


def nombre_de_agente_catalogo(agente: dict) -> str:
    partes = [(agente.get("firstname") or "").strip(), (agente.get("lastname") or "").strip()]
    nombre = " ".join(p for p in partes if p) or (agente.get("email") or "").strip()
    nombre = nombre or f"Agente {agente.get('id')}"
    extension = agente.get("extension")
    return f"{nombre} (ext. {extension})" if extension else nombre


def opciones_agentes(agentes: list[dict]) -> dict[str, str]:
    """id → etiqueta, ordenado por nombre."""
    opciones = {
        str(a["id"]): nombre_de_agente_catalogo(a) for a in agentes if a.get("id")
    }
    return dict(sorted(opciones.items(), key=lambda par: par[1].lower()))


def opciones_numeros(numeros: list[dict]) -> dict[str, str]:
    opciones = {}
    for numero in numeros:
        if not numero.get("id"):
            continue
        nombre = (numero.get("internal_name") or "").strip()
        telefono = numero.get("caller_id_e164")
        telefono = f"+{_digitos(telefono)}" if telefono else ""
        opciones[str(numero["id"])] = " · ".join(p for p in (nombre, telefono) if p)
    return dict(sorted(opciones.items(), key=lambda par: par[1].lower()))


def opciones_grupos(grupos: list[dict]) -> list[str]:
    nombres = {(g.get("internal_name") or "").strip() for g in grupos}
    return sorted((n for n in nombres if n), key=str.lower)


def escribir_csv(filas: list[dict[str, str]]) -> bytes:
    """CSV con BOM para que Excel en Windows respete los acentos."""
    memoria = io.StringIO()
    escritor = csv.DictWriter(memoria, fieldnames=list(COLUMNAS), lineterminator="\r\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return memoria.getvalue().encode("utf-8-sig")


def nombre_archivo(desde: date, hasta: date) -> str:
    return f"reporte-cloudtalk-{desde:%Y-%m-%d}-a-{hasta:%Y-%m-%d}.csv"
