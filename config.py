"""Lectura y validación de la configuración por variables de entorno."""

from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict

DATA_DIR_POR_DEFECTO = "/data"
RINGOVER_BASE_URL_POR_DEFECTO = "https://public-api.ringover.com/v2"
CLOUDTALK_BASE_URL_POR_DEFECTO = "https://my.cloudtalk.io/api"
CLOUDTALK_AI_BASE_URL_POR_DEFECTO = "https://api.cloudtalk.io/v1"

# SQLAlchemy necesita el nombre del driver en la URL. EasyPanel y la mayoría de
# los proveedores entregan `postgres://` o `postgresql://` sin él.
DRIVER_POSTGRES = "postgresql+psycopg"
_ESQUEMAS_POSTGRES = ("postgres", "postgresql")

SYNC_INTERVALO_MINUTOS_POR_DEFECTO = 15
SYNC_DIAS_INICIALES_POR_DEFECTO = 30
CHATWOOT_DIAS_RELECTURA_POR_DEFECTO = 14

_REQUERIDAS = (
    "CHATWOOT_BASE_URL",
    "CHATWOOT_ACCOUNT_ID",
    "CHATWOOT_API_TOKEN",
    "APP_USERNAME",
    "APP_PASSWORD_HASH",
    "APP_COOKIE_KEY",
    "DATABASE_URL",
)


class ConfigError(Exception):
    """La configuración del entorno es inválida o está incompleta."""


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: str
    account_id: int
    api_token: str
    usuario: str
    password_hash: str
    cookie_key: str
    database_url: str
    data_dir: Path
    # Ringover es opcional: sin token, la app funciona igual y solo se oculta
    # la pestaña de transcripciones.
    ringover_token: str = ""
    ringover_base_url: str = RINGOVER_BASE_URL_POR_DEFECTO
    # CloudTalk también es opcional y necesita el par id + secreto de la clave.
    cloudtalk_key_id: str = ""
    cloudtalk_key_secret: str = ""
    cloudtalk_base_url: str = CLOUDTALK_BASE_URL_POR_DEFECTO
    cloudtalk_ai_base_url: str = CLOUDTALK_AI_BASE_URL_POR_DEFECTO
    # Sincronización (proceso `python -m panel.sync`).
    sync_intervalo_minutos: int = SYNC_INTERVALO_MINUTOS_POR_DEFECTO
    # Hasta dónde mira hacia atrás la primera sincronización de cada fuente.
    sync_dias_iniciales: int = SYNC_DIAS_INICIALES_POR_DEFECTO
    # Las conversaciones cambian después de creadas (se resuelven, se
    # reasignan), así que cada ciclo relee las de estos últimos días.
    chatwoot_dias_relectura: int = CHATWOOT_DIAS_RELECTURA_POR_DEFECTO

    @property
    def cloudtalk_configurado(self) -> bool:
        return bool(self.cloudtalk_key_id and self.cloudtalk_key_secret)


def normalizar_url_bd(bruta: str) -> str:
    """Devuelve la URL de Postgres con el driver que usa SQLAlchemy."""
    url = bruta.strip()
    esquema, separador, resto = url.partition("://")
    if not separador:
        raise ConfigError(
            "DATABASE_URL debe tener la forma postgresql://usuario:clave@host:5432/base"
        )
    if esquema in _ESQUEMAS_POSTGRES:
        return f"{DRIVER_POSTGRES}://{resto}"
    if esquema.startswith("postgresql+"):
        return url
    raise ConfigError(
        f"DATABASE_URL debe apuntar a PostgreSQL, se recibió el esquema {esquema!r}."
    )


def _entero_positivo(entorno: Mapping[str, str], nombre: str, defecto: int) -> int:
    bruto = (entorno.get(nombre) or "").strip()
    if not bruto:
        return defecto
    try:
        valor = int(bruto)
    except ValueError:
        valor = 0
    if valor < 1:
        raise ConfigError(f"{nombre} debe ser un número entero mayor que cero, se recibió: {bruto!r}")
    return valor


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
        database_url=normalizar_url_bd(entorno["DATABASE_URL"]),
        data_dir=Path(data_dir),
        ringover_token=entorno.get("RINGOVER_API_TOKEN", "").strip(),
        ringover_base_url=(
            entorno.get("RINGOVER_BASE_URL") or RINGOVER_BASE_URL_POR_DEFECTO
        ).strip().rstrip("/"),
        cloudtalk_key_id=entorno.get("CLOUDTALK_API_KEY_ID", "").strip(),
        cloudtalk_key_secret=entorno.get("CLOUDTALK_API_KEY_SECRET", "").strip(),
        cloudtalk_base_url=(
            entorno.get("CLOUDTALK_BASE_URL") or CLOUDTALK_BASE_URL_POR_DEFECTO
        ).strip().rstrip("/"),
        cloudtalk_ai_base_url=(
            entorno.get("CLOUDTALK_AI_BASE_URL") or CLOUDTALK_AI_BASE_URL_POR_DEFECTO
        ).strip().rstrip("/"),
        sync_intervalo_minutos=_entero_positivo(
            entorno, "SYNC_INTERVALO_MINUTOS", SYNC_INTERVALO_MINUTOS_POR_DEFECTO
        ),
        sync_dias_iniciales=_entero_positivo(
            entorno, "SYNC_DIAS_INICIALES", SYNC_DIAS_INICIALES_POR_DEFECTO
        ),
        chatwoot_dias_relectura=_entero_positivo(
            entorno, "CHATWOOT_DIAS_RELECTURA", CHATWOOT_DIAS_RELECTURA_POR_DEFECTO
        ),
    )


def ruta_asesores(cfg: Config) -> Path:
    """El archivo de asesores anterior a la base de datos; solo se lee una vez
    para importarlo."""
    return cfg.data_dir / "asesores.csv"


def ruta_cache(cfg: Config) -> Path:
    return cfg.data_dir / "cache"
