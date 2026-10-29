"""Lectura y validación de la configuración por variables de entorno."""

from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

DATA_DIR_POR_DEFECTO = "/data"
RINGOVER_BASE_URL_POR_DEFECTO = "https://public-api.ringover.com/v2"
CLOUDTALK_BASE_URL_POR_DEFECTO = "https://my.cloudtalk.io/api"
CLOUDTALK_AI_BASE_URL_POR_DEFECTO = "https://api.cloudtalk.io/v1"

# SQLAlchemy necesita el nombre del driver en la URL. EasyPanel y la mayoría de
# los proveedores entregan `postgres://` o `postgresql://` sin él.
DRIVER_POSTGRES = "postgresql+psycopg"
_ESQUEMAS_POSTGRES = ("postgres", "postgresql")

ALMACENES = ("", "local", "sftp")
SFTP_PUERTO_POR_DEFECTO = 22
AUDIO_RETENCION_DIAS_POR_DEFECTO = 90

TRANSCRIPCION_RETENCION_DIAS_POR_DEFECTO = 1095
TRANSCRIPCION_POR_CICLO_POR_DEFECTO = 20
CANALES_AGENTE = ("izquierdo", "derecho")

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
    # Almacén de los MP3 escuchados: vacío (no se guardan), «local» (una
    # carpeta en DATA_DIR, para desarrollo) o «sftp» (el hosting).
    almacen_tipo: str = ""
    ftp_host: str = ""
    ftp_port: int = SFTP_PUERTO_POR_DEFECTO
    ftp_user: str = ""
    ftp_password: str = ""
    ftp_dir: str = "/"
    sftp_huella_host: str = ""
    audio_retencion_dias: int = AUDIO_RETENCION_DIAS_POR_DEFECTO
    # Transcripción. El proveedor es el nombre de una estrategia registrada
    # (panel/transcripcion/estrategias); vacío, la transcripción está apagada.
    transcripcion_proveedor: str = ""
    transcripcion_respaldo: tuple[str, ...] = ()
    transcripcion_idioma: str = "es"
    transcripcion_vocabulario: tuple[str, ...] = ()
    # En una grabación estéreo, qué canal es el del agente.
    cloudtalk_canal_agente: str = "izquierdo"
    transcripcion_retencion_dias: int = TRANSCRIPCION_RETENCION_DIAS_POR_DEFECTO
    transcripcion_por_ciclo: int = TRANSCRIPCION_POR_CICLO_POR_DEFECTO
    # Las variables de entorno tal cual, para que cada estrategia lea las suyas
    # (OPENAI_API_KEY…) sin que esta clase tenga que conocerlas. No se muestran.
    entorno: dict[str, str] = Field(default_factory=dict, repr=False)

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


def _almacen(entorno: Mapping[str, str]) -> dict:
    tipo = (entorno.get("ALMACEN_TIPO") or "").strip().lower()
    if tipo not in ALMACENES:
        raise ConfigError(
            f"ALMACEN_TIPO debe ser «local» o «sftp» (o quedar vacío), se recibió: {tipo!r}"
        )
    datos = {
        "almacen_tipo": tipo,
        "ftp_host": (entorno.get("FTP_HOST") or "").strip(),
        "ftp_port": _entero_positivo(entorno, "FTP_PORT", SFTP_PUERTO_POR_DEFECTO),
        "ftp_user": (entorno.get("FTP_USER") or "").strip(),
        # La clave no se recorta: un espacio puede ser parte de ella.
        "ftp_password": entorno.get("FTP_PASSWORD") or "",
        "ftp_dir": (entorno.get("FTP_DIR") or "/").strip() or "/",
        "sftp_huella_host": (entorno.get("SFTP_HUELLA_HOST") or "").strip(),
        "audio_retencion_dias": _entero_positivo(
            entorno, "AUDIO_RETENCION_DIAS", AUDIO_RETENCION_DIAS_POR_DEFECTO
        ),
    }
    if tipo == "sftp":
        requeridas = {
            "FTP_HOST": datos["ftp_host"],
            "FTP_USER": datos["ftp_user"],
            "FTP_PASSWORD": datos["ftp_password"],
            "SFTP_HUELLA_HOST": datos["sftp_huella_host"],
        }
        faltantes = [nombre for nombre, valor in requeridas.items() if not valor]
        if faltantes:
            raise ConfigError(
                "Con ALMACEN_TIPO=sftp faltan: " + ", ".join(faltantes)
                + ". La huella se obtiene con «python -m panel.audio.huella HOST PUERTO»."
            )
    return datos


def _lista(entorno: Mapping[str, str], nombre: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in (entorno.get(nombre) or "").split(",") if p.strip())


def _transcripcion(entorno: Mapping[str, str]) -> dict:
    proveedor = (entorno.get("TRANSCRIPCION_PROVEEDOR") or "").strip().lower()
    if not proveedor and (entorno.get("OPENAI_API_KEY") or "").strip():
        proveedor = "openai"
    canal = (entorno.get("CLOUDTALK_CANAL_AGENTE") or "izquierdo").strip().lower()
    if canal not in CANALES_AGENTE:
        raise ConfigError(
            f"CLOUDTALK_CANAL_AGENTE debe ser «izquierdo» o «derecho», se recibió: {canal!r}"
        )
    return {
        "transcripcion_proveedor": proveedor,
        "transcripcion_respaldo": tuple(p.lower() for p in _lista(entorno, "TRANSCRIPCION_RESPALDO")),
        "transcripcion_idioma": (entorno.get("TRANSCRIPCION_IDIOMA") or "es").strip(),
        "transcripcion_vocabulario": _lista(entorno, "TRANSCRIPCION_VOCABULARIO"),
        "cloudtalk_canal_agente": canal,
        "transcripcion_retencion_dias": _entero_positivo(
            entorno, "TRANSCRIPCION_RETENCION_DIAS", TRANSCRIPCION_RETENCION_DIAS_POR_DEFECTO
        ),
        "transcripcion_por_ciclo": _entero_positivo(
            entorno, "TRANSCRIPCION_POR_CICLO", TRANSCRIPCION_POR_CICLO_POR_DEFECTO
        ),
        "entorno": dict(entorno),
    }


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
        **_almacen(entorno),
        **_transcripcion(entorno),
    )


def ruta_asesores(cfg: Config) -> Path:
    """El archivo de asesores anterior a la base de datos; solo se lee una vez
    para importarlo."""
    return cfg.data_dir / "asesores.csv"


def ruta_cache(cfg: Config) -> Path:
    return cfg.data_dir / "cache"


def ruta_audios_locales(cfg: Config) -> Path:
    return cfg.data_dir / "audios"
