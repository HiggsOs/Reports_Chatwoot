"""Quién es el agente cuando el proveedor separó las voces sin saberlo.

El proveedor devuelve «Hablante A», «Hablante B»… El agente se reconoce por
lo que dice: el saludo de la empresa («servicio de grúa», «grúa privada»…).
Las frases se configuran en Transcripción › Configuración.

Si el proveedor no separó las voces (todo quedó como un solo hablante), no se
puede decidir por etiqueta: el auditor marca frase por frase.
"""

import re
import unicodedata

from pydantic import BaseModel

from panel.transcripcion.base import Segmento

# Se comparan sin acentos ni mayúsculas.
FRASES_AGENTE_POR_DEFECTO = (
    "servicio de grúa",
    "servicio de grúas",
    "grúa privada",
    "grúas privadas",
    "le atiende",
    "le habla",
    "en qué le puedo ayudar",
    "en qué puedo ayudarle",
    "en qué le podemos ayudar",
)


class Sugerencia(BaseModel):
    etiqueta: str  # la del agente («A», «B»…)
    frase: str  # lo que dijo, tal cual


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos ni signos: «¡Buen día, Grúa Privada!» → «buen dia grua privada»."""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9ñ]+", " ", sin_acentos.lower()).split())


def identificar_agente(segmentos: list[Segmento], frases: tuple[str, ...]) -> Sugerencia | None:
    """La etiqueta del agente según las frases que dice, o None si no se sabe.

    Solo mira las voces sin resolver. Si más de una voz dice frases del agente,
    gana la que dice más frases distintas; empate: la que lo dijo primero.
    Hace falta al menos dos voces: con una sola no hay a quién separar.
    """
    patrones = [(frase, re.compile(rf"\b{re.escape(normalizar(frase))}\b")) for frase in frases if normalizar(frase)]
    etiquetas = {s.etiqueta for s in segmentos if s.etiqueta and s.hablante == "desconocido"}
    if len(etiquetas) < 2 or not patrones:
        return None
    encontradas: dict[str, set[str]] = {}
    primera: dict[str, tuple[int, str]] = {}
    for orden, segmento in enumerate(segmentos):
        if segmento.etiqueta not in etiquetas:
            continue
        texto = normalizar(segmento.texto)
        for frase, patron in patrones:
            if patron.search(texto):
                encontradas.setdefault(segmento.etiqueta, set()).add(frase)
                primera.setdefault(segmento.etiqueta, (orden, segmento.texto.strip()))
    if not encontradas:
        return None
    etiqueta = min(encontradas, key=lambda e: (-len(encontradas[e]), primera[e][0]))
    return Sugerencia(etiqueta=etiqueta, frase=primera[etiqueta][1])


def roles_para(segmentos: list[Segmento], agente: str) -> dict[str, str]:
    """{"A": "agente", "B": "cliente"}: el resto de las voces son el cliente."""
    etiquetas = {s.etiqueta for s in segmentos if s.etiqueta}
    return {e: ("agente" if e == agente else "cliente") for e in etiquetas}


def aplicar_roles(segmentos: list[Segmento], roles: dict[str, str]) -> list[Segmento]:
    return [
        s.model_copy(update={"hablante": roles[s.etiqueta]}) if s.etiqueta in roles else s
        for s in segmentos
    ]
