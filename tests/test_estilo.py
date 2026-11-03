from decimal import Decimal

from ui.componentes.estilo import etiqueta_asignacion, insignia, numero, usd


def test_numeros_en_formato_espanol():
    assert numero(1234.5) == "1.234,50"
    assert numero(Decimal("0.0066"), 4) == "0,0066"
    assert numero(None) == "—"
    assert usd(41.24) == "41,24 USD"


def test_insignia_escapa_el_texto():
    assert "&lt;b&gt;" in insignia("<b>", "error")


def test_etiqueta_de_asignacion():
    assert etiqueta_asignacion("", "automática") == "Sin asignar"
    assert etiqueta_asignacion("Ana", "manual") == "Manual"
    assert etiqueta_asignacion("Ana", "automática") == "Regla"
