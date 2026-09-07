from pathlib import Path

import pytest

from config import Config, ConfigError, cargar_config, ruta_asesores, ruta_cache

ENTORNO_VALIDO = {
    "CHATWOOT_BASE_URL": "https://chat.ejemplo.com/",
    "CHATWOOT_ACCOUNT_ID": "3",
    "CHATWOOT_API_TOKEN": "token-secreto",
    "APP_USERNAME": "reportes",
    "APP_PASSWORD_HASH": "$2b$12$abcdefghijklmnopqrstuv",
    "APP_COOKIE_KEY": "clave-de-cookie",
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
