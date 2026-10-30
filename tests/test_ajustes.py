import pytest
from sqlalchemy import select

from panel.ajustes import (
    AjusteDesconocido,
    Cifrador,
    RepositorioAjustes,
    enmascarar,
    entorno_efectivo,
    origenes,
)
from panel.db.modelos import Ajuste


def test_cifrar_y_descifrar():
    cifrador = Cifrador("una llave")
    cifrado = cifrador.cifrar("secreto")
    assert cifrado != "secreto"
    assert cifrador.descifrar(cifrado) == "secreto"


def test_la_llave_sale_de_panel_clave_cifrado_o_de_la_cookie():
    texto = Cifrador("cookie").cifrar("x")
    assert Cifrador.desde_entorno({"APP_COOKIE_KEY": "cookie"}).descifrar(texto) == "x"
    propia = Cifrador.desde_entorno({"APP_COOKIE_KEY": "cookie", "PANEL_CLAVE_CIFRADO": "otra"})
    assert propia.descifrar(Cifrador("otra").cifrar("y")) == "y"


def test_sin_llave_no_se_puede_cifrar():
    with pytest.raises(ValueError):
        Cifrador("  ")


def test_enmascarar_muestra_solo_el_final():
    assert enmascarar("sk-abcdefgh1234") == "••••••••••••1234"
    assert enmascarar("corta") == "••••••••"
    assert enmascarar("") == ""


def test_guarda_los_secretos_cifrados(fabrica):
    cifrador = Cifrador("llave")
    with fabrica() as sesion:
        repo = RepositorioAjustes(sesion, cifrador)
        repo.guardar({"CHATWOOT_API_TOKEN": "token-1", "CHATWOOT_BASE_URL": "https://chat.x"})
        sesion.flush()
        filas = {f.clave: f for f in sesion.scalars(select(Ajuste))}
        assert filas["CHATWOOT_API_TOKEN"].secreto
        assert filas["CHATWOOT_API_TOKEN"].valor != "token-1"
        assert filas["CHATWOOT_BASE_URL"].valor == "https://chat.x"
        assert repo.leer().valores == {
            "CHATWOOT_API_TOKEN": "token-1",
            "CHATWOOT_BASE_URL": "https://chat.x",
        }


def test_vacio_borra_el_ajuste(fabrica):
    with fabrica() as sesion:
        repo = RepositorioAjustes(sesion, Cifrador("llave"))
        repo.guardar({"FTP_HOST": "a.com"})
        sesion.flush()
        repo.guardar({"FTP_HOST": ""})
        sesion.flush()
        assert repo.leer().valores == {}


def test_no_acepta_ajustes_desconocidos(fabrica):
    with fabrica() as sesion:
        with pytest.raises(AjusteDesconocido):
            RepositorioAjustes(sesion, Cifrador("llave")).guardar({"DATABASE_URL": "x"})


def test_un_secreto_de_otra_llave_queda_ilegible(fabrica):
    with fabrica() as sesion:
        RepositorioAjustes(sesion, Cifrador("vieja")).guardar({"FTP_PASSWORD": "clave"})
        sesion.flush()
        lectura = RepositorioAjustes(sesion, Cifrador("nueva")).leer()
    assert lectura.valores == {}
    assert lectura.ilegibles == ["FTP_PASSWORD"]


def test_el_panel_pisa_al_entorno(fabrica):
    entorno = {"APP_COOKIE_KEY": "llave", "FTP_HOST": "entorno.com", "FTP_USER": "u"}
    with fabrica() as sesion:
        RepositorioAjustes(sesion, Cifrador("llave")).guardar({"FTP_HOST": "panel.com"})
        sesion.commit()
    efectivo, lectura = entorno_efectivo(entorno, fabrica)
    assert efectivo["FTP_HOST"] == "panel.com"
    assert efectivo["FTP_USER"] == "u"
    assert origenes(entorno, lectura)["FTP_HOST"] == "panel"
    assert origenes(entorno, lectura)["FTP_USER"] == "entorno"
    assert "FTP_PASSWORD" not in origenes(entorno, lectura)
