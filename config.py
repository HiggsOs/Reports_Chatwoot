"""Lectura y validación de la configuración por variables de entorno."""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DATA_DIR_POR_DEFECTO = "/data"
RINGOVER_BASE_URL_POR_DEFECTO = "https://public-api.ringover.com/v2"

_REQUERIDAS = (
    "CHATWOOT_BASE_URL",
    "CHATWOOT_ACCOUNT_ID",
    "CHATWOOT_API_TOKEN",
    "APP_USERNAME",
    "APP_PASSWORD_HASH",
    "APP_COOKIE_KEY",
)


class ConfigError(Exception):
    """La configuración del entorno es inválida o está incompleta."""


@dataclass(frozen=True)
class Config:
    base_url: str
    account_id: int
    api_token: str
    usuario: str
    password_hash: str
    cookie_key: str
    data_dir: Path
    # Ringover es opcional: sin token, la app funciona igual y solo se oculta
    # la pestaña de transcripciones.
    ringover_token: str = ""
    ringover_base_url: str = RINGOVER_BASE_URL_POR_DEFECTO


def cargar_config(entorno: Mapping[str, str]) -> Config:
    faltantes = [
        nombre for nombre in _REQUERIDAS if not entorno.get(nombre, "").strip()
    ]
    if faltantes:
        raise ConfigError(
            "Faltan variables de entorno obligatorias: " + ", ".join(faltantes)
        )

    bruto = entorno["CHATWOOT_ACCOUNT_ID"].strip()
    try:
        account_id = int(bruto)
    except ValueError as error:
        raise ConfigError(
            f"CHATWOOT_ACCOUNT_ID debe ser un número entero, se recibió: {bruto!r}"
        ) from error

    data_dir = (entorno.get("DATA_DIR") or DATA_DIR_POR_DEFECTO).strip()

    return Config(
        base_url=entorno["CHATWOOT_BASE_URL"].strip().rstrip("/"),
        account_id=account_id,
        api_token=entorno["CHATWOOT_API_TOKEN"].strip(),
        usuario=entorno["APP_USERNAME"].strip(),
        password_hash=entorno["APP_PASSWORD_HASH"].strip(),
        cookie_key=entorno["APP_COOKIE_KEY"].strip(),
        data_dir=Path(data_dir),
        ringover_token=entorno.get("RINGOVER_API_TOKEN", "").strip(),
        ringover_base_url=(
            entorno.get("RINGOVER_BASE_URL") or RINGOVER_BASE_URL_POR_DEFECTO
        ).strip().rstrip("/"),
    )


def ruta_asesores(cfg: Config) -> Path:
    return cfg.data_dir / "asesores.csv"


def ruta_cache(cfg: Config) -> Path:
    return cfg.data_dir / "cache"
