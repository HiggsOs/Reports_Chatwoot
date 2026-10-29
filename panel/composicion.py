"""Raíz de composición: el único lugar que arma piezas concretas.

Lee la configuración y decide qué clientes, fuentes y sincronizadores se usan.
El resto del sistema recibe esas piezas ya armadas.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from chatwoot import ClienteChatwoot
from cloudtalk import ClienteCloudTalk
from config import Config, ruta_audios_locales
from panel.audio.almacen import AlmacenAudio, AlmacenLocal, AlmacenSFTP
from panel.audio.servicio import ServicioAudio
from panel.fuentes.interacciones import FuenteChatwoot, FuenteCloudTalk
from panel.sync.sincronizadores import (
    Sincronizador,
    SincronizadorConversaciones,
    SincronizadorLlamadas,
)
from panel.sync.tareas import (
    ProcesarTranscripciones,
    RetencionDeAudios,
    RetencionDeTranscripciones,
    SubirAudiosPendientes,
    Tarea,
)
from panel.transcripcion import registro as registro_transcripcion
from panel.transcripcion.base import OpcionesTranscripcion
from panel.transcripcion.servicio import ServicioTranscripcion


def cliente_cloudtalk(cfg: Config) -> ClienteCloudTalk:
    return ClienteCloudTalk(
        cfg.cloudtalk_key_id,
        cfg.cloudtalk_key_secret,
        cfg.cloudtalk_base_url,
        cfg.cloudtalk_ai_base_url,
    )


def almacen_de_audio(cfg: Config) -> AlmacenAudio | None:
    if cfg.almacen_tipo == "sftp":
        return AlmacenSFTP(
            cfg.ftp_host,
            cfg.ftp_port,
            cfg.ftp_user,
            cfg.ftp_password,
            cfg.ftp_dir,
            cfg.sftp_huella_host,
        )
    if cfg.almacen_tipo == "local":
        return AlmacenLocal(ruta_audios_locales(cfg))
    return None


def servicio_audio(fabrica: sessionmaker[Session], cfg: Config) -> ServicioAudio | None:
    """None si CloudTalk no está configurado: no hay de dónde traer el audio."""
    if not cfg.cloudtalk_configurado:
        return None
    return ServicioAudio(
        fabrica,
        FuenteCloudTalk(cliente_cloudtalk(cfg)),
        almacen_de_audio(cfg),
        cfg.audio_retencion_dias,
    )


def servicio_transcripcion(
    fabrica: sessionmaker[Session], cfg: Config, audio: ServicioAudio | None
) -> ServicioTranscripcion | None:
    """None si no hay de dónde sacar el audio o si el proveedor elegido no está
    configurado (por ejemplo, falta su clave)."""
    if audio is None or not cfg.transcripcion_proveedor:
        return None
    estrategias = registro_transcripcion.disponibles(cfg.entorno)
    cadena = [cfg.transcripcion_proveedor, *cfg.transcripcion_respaldo]
    if cfg.transcripcion_proveedor not in estrategias:
        return None
    return ServicioTranscripcion(
        fabrica,
        audio,
        estrategias,
        cadena,
        OpcionesTranscripcion(
            idioma=cfg.transcripcion_idioma, vocabulario=cfg.transcripcion_vocabulario
        ),
        cfg.cloudtalk_canal_agente,
    )


def sincronizadores(fabrica: sessionmaker[Session], cfg: Config) -> list[Sincronizador | Tarea]:
    """Lo que corre en cada ciclo: primero traer datos, después mantenimiento."""
    desde_inicial = datetime.now(timezone.utc) - timedelta(days=cfg.sync_dias_iniciales)
    lista: list[Sincronizador | Tarea] = []
    if cfg.cloudtalk_configurado:
        fuente = FuenteCloudTalk(cliente_cloudtalk(cfg))
        lista.append(SincronizadorLlamadas(fabrica, fuente, desde_inicial))
    chatwoot = ClienteChatwoot(cfg.base_url, cfg.account_id, cfg.api_token)
    lista.append(
        SincronizadorConversaciones(
            fabrica, FuenteChatwoot(chatwoot), desde_inicial, cfg.chatwoot_dias_relectura
        )
    )
    audio = servicio_audio(fabrica, cfg)
    if audio is not None and audio.guarda_audios:
        lista.append(SubirAudiosPendientes(fabrica, audio))
        lista.append(RetencionDeAudios(fabrica, audio))
    transcripcion = servicio_transcripcion(fabrica, cfg, audio)
    if transcripcion is not None:
        lista.append(ProcesarTranscripciones(fabrica, transcripcion, cfg.transcripcion_por_ciclo))
    # La retención de transcripciones corre aunque no haya proveedor: las ya
    # guardadas también vencen.
    lista.append(RetencionDeTranscripciones(fabrica, cfg.transcripcion_retencion_dias))
    return lista
