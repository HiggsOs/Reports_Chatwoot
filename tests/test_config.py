from pathlib import Path

import pytest

from config import (
    Config,
    ConfigError,
    cargar_config,
    normalizar_url_bd,
    ruta_asesores,
    ruta_cache,
)

ENTORNO_VALIDO = {
    "CHATWOOT_BASE_URL": "https://chat.ejemplo.com/",
    "CHATWOOT_ACCOUNT_ID": "3",
    "CHATWOOT_API_TOKEN": "token-secreto",
    "APP_USERNAME": "reportes",
    "APP_PASSWORD_HASH": "$2b$12$abcdefghijklmnopqrstuv",
    "APP_COOKIE_KEY": "clave-de-cookie",
    "DATABASE_URL": "postgres://panel:clave@postgres:5432/panel",
    "DATA_DIR": "/data",
}


def test_carga_configuracion_completa():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert isinstance(cfg, Config)
    assert cfg.account_id == 3
    assert cfg.api_token == "token-secreto"
    assert cfg.data_dir == Path("/data")


def test_quita_la_barra_final_de_la_url():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert cfg.base_url == "https://chat.ejemplo.com"


def test_data_dir_tiene_valor_por_defecto():
    entorno = {k: v for k, v in ENTORNO_VALIDO.items() if k != "DATA_DIR"}
    assert cargar_config(entorno).data_dir == Path("/data")


def test_falta_una_variable():
    entorno = {k: v for k, v in ENTORNO_VALIDO.items() if k != "CHATWOOT_API_TOKEN"}
    with pytest.raises(ConfigError) as error:
        cargar_config(entorno)
    assert "CHATWOOT_API_TOKEN" in str(error.value)


def test_variable_vacia_cuenta_como_faltante():
    with pytest.raises(ConfigError) as error:
        cargar_config({**ENTORNO_VALIDO, "APP_COOKIE_KEY": "   "})
    assert "APP_COOKIE_KEY" in str(error.value)


def test_reporta_todas_las_variables_faltantes_juntas():
    with pytest.raises(ConfigError) as error:
        cargar_config({"CHATWOOT_BASE_URL": "https://x.com"})
    mensaje = str(error.value)
    assert "CHATWOOT_ACCOUNT_ID" in mensaje
    assert "APP_USERNAME" in mensaje


def test_account_id_no_numerico():
    with pytest.raises(ConfigError) as error:
        cargar_config({**ENTORNO_VALIDO, "CHATWOOT_ACCOUNT_ID": "abc"})
    assert "CHATWOOT_ACCOUNT_ID" in str(error.value)


def test_rutas_derivadas_del_data_dir():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert ruta_asesores(cfg) == Path("/data/asesores.csv")
    assert ruta_cache(cfg) == Path("/data/cache")


def test_ringover_es_opcional_y_trae_url_por_defecto():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert cfg.ringover_token == ""
    assert cfg.ringover_base_url == "https://public-api.ringover.com/v2"


def test_ringover_toma_token_y_url_del_entorno():
    cfg = cargar_config(
        {
            **ENTORNO_VALIDO,
            "RINGOVER_API_TOKEN": "  token-ringover  ",
            "RINGOVER_BASE_URL": "https://public-api-us.ringover.com/v2/",
        }
    )
    assert cfg.ringover_token == "token-ringover"
    assert cfg.ringover_base_url == "https://public-api-us.ringover.com/v2"


def test_cloudtalk_es_opcional():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert not cfg.cloudtalk_configurado
    assert cfg.cloudtalk_base_url == "https://my.cloudtalk.io/api"
    assert cfg.cloudtalk_ai_base_url == "https://api.cloudtalk.io/v1"


def test_cloudtalk_necesita_id_y_secreto():
    solo_id = cargar_config({**ENTORNO_VALIDO, "CLOUDTALK_API_KEY_ID": "abc"})
    assert not solo_id.cloudtalk_configurado

    completo = cargar_config(
        {
            **ENTORNO_VALIDO,
            "CLOUDTALK_API_KEY_ID": " abc ",
            "CLOUDTALK_API_KEY_SECRET": "xyz",
        }
    )
    assert completo.cloudtalk_configurado
    assert completo.cloudtalk_key_id == "abc"


def test_database_url_es_obligatoria():
    entorno = {k: v for k, v in ENTORNO_VALIDO.items() if k != "DATABASE_URL"}
    with pytest.raises(ConfigError) as error:
        cargar_config(entorno)
    assert "DATABASE_URL" in str(error.value)


def test_database_url_agrega_el_driver():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert cfg.database_url == "postgresql+psycopg://panel:clave@postgres:5432/panel"


@pytest.mark.parametrize(
    "bruta",
    [
        "postgres://u:c@h:5432/b",
        "postgresql://u:c@h:5432/b",
        "  postgresql+psycopg://u:c@h:5432/b  ",
    ],
)
def test_normalizar_url_bd_acepta_las_formas_de_postgres(bruta):
    assert normalizar_url_bd(bruta) == "postgresql+psycopg://u:c@h:5432/b"


def test_normalizar_url_bd_respeta_otro_driver_de_postgres():
    assert normalizar_url_bd("postgresql+asyncpg://u@h/b") == "postgresql+asyncpg://u@h/b"


@pytest.mark.parametrize("bruta", ["mysql://u@h/b", "sqlite:///panel.db", "host:5432"])
def test_normalizar_url_bd_rechaza_lo_que_no_es_postgres(bruta):
    with pytest.raises(ConfigError) as error:
        normalizar_url_bd(bruta)
    assert "DATABASE_URL" in str(error.value)


def test_config_es_inmutable():
    cfg = cargar_config(ENTORNO_VALIDO)
    with pytest.raises(ValueError):
        cfg.account_id = 9


def test_la_sincronizacion_trae_valores_por_defecto():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert (cfg.sync_intervalo_minutos, cfg.sync_dias_iniciales, cfg.chatwoot_dias_relectura) == (
        15,
        30,
        14,
    )


def test_la_sincronizacion_toma_sus_valores_del_entorno():
    cfg = cargar_config({**ENTORNO_VALIDO, "SYNC_INTERVALO_MINUTOS": " 5 ", "SYNC_DIAS_INICIALES": "90"})
    assert (cfg.sync_intervalo_minutos, cfg.sync_dias_iniciales) == (5, 90)


@pytest.mark.parametrize("valor", ["0", "-3", "diez", "1.5"])
def test_la_sincronizacion_rechaza_valores_no_positivos(valor):
    with pytest.raises(ConfigError) as error:
        cargar_config({**ENTORNO_VALIDO, "SYNC_INTERVALO_MINUTOS": valor})
    assert "SYNC_INTERVALO_MINUTOS" in str(error.value)
