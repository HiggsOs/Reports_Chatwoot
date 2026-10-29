"""Raíz de composición: el único lugar que arma piezas concretas.

Lee la configuración y decide qué clientes, fuentes y sincronizadores se usan.
El resto del sistema recibe esas piezas ya armadas.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from chatwoot import ClienteChatwoot
from cloudtalk import ClienteCloudTalk
from config import Config
from panel.fuentes.interacciones import FuenteChatwoot, FuenteCloudTalk
from panel.sync.sincronizadores import (
    Sincronizador,
    SincronizadorConversaciones,
    SincronizadorLlamadas,
)


def sincronizadores(fabrica: sessionmaker[Session], cfg: Config) -> list[Sincronizador]:
    desde_inicial = datetime.now(timezone.utc) - timedelta(days=cfg.sync_dias_iniciales)
    lista: list[Sincronizador] = []
    if cfg.cloudtalk_configurado:
        cliente = ClienteCloudTalk(
            cfg.cloudtalk_key_id,
            cfg.cloudtalk_key_secret,
            cfg.cloudtalk_base_url,
            cfg.cloudtalk_ai_base_url,
        )
        lista.append(SincronizadorLlamadas(fabrica, FuenteCloudTalk(cliente), desde_inicial))
    chatwoot = ClienteChatwoot(cfg.base_url, cfg.account_id, cfg.api_token)
    lista.append(
        SincronizadorConversaciones(
            fabrica, FuenteChatwoot(chatwoot), desde_inicial, cfg.chatwoot_dias_relectura
        )
    )
    return lista
