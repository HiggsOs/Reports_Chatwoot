"""Normalización de teléfonos al formato internacional E.164.

Un mismo cliente llega como «612 345 678», «34612345678» o «+34 612 34 56 78»
según la plataforma, y tiene que ser un solo cliente. Sin código de país se
supone España.
"""

import re

import phonenumbers
from pydantic import BaseModel, ConfigDict

REGION_POR_DEFECTO = "ES"


class Telefono(BaseModel):
    model_config = ConfigDict(frozen=True)

    # E.164 si se pudo interpretar; si no, solo los dígitos.
    valor: str
    original: str
    # No se pudo interpretar como un número válido: hay que mirarlo a mano.
    revisar: bool


def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _valido(texto: str, region: str | None) -> str | None:
    try:
        numero = phonenumbers.parse(texto, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(numero):
        return None
    return phonenumbers.format_number(numero, phonenumbers.PhoneNumberFormat.E164)


def normalizar(texto: str | None, region: str = REGION_POR_DEFECTO) -> Telefono | None:
    """Devuelve None si no hay ningún dígito."""
    original = (texto or "").strip()
    digitos = _digitos(original)
    if not digitos:
        return None

    e164 = _valido(original, region)
    if e164 is None and not original.startswith("+") and len(digitos) >= 10:
        # «573001234567»: un número extranjero con su código de país pero sin «+».
        e164 = _valido(f"+{digitos}", None)
    if e164 is None:
        return Telefono(valor=digitos, original=original, revisar=True)
    return Telefono(valor=e164, original=original, revisar=False)
