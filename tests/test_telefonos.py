import pytest

from panel.telefonos import normalizar


@pytest.mark.parametrize(
    "texto",
    ["612 345 678", "34612345678", "0034 612 345 678", "+34 612 34 56 78", "+34612345678"],
)
def test_las_formas_de_un_movil_español_son_el_mismo_numero(texto):
    telefono = normalizar(texto)
    assert telefono.valor == "+34612345678"
    assert not telefono.revisar
    assert telefono.original == texto.strip()


def test_un_fijo_español():
    assert normalizar("912 345 678").valor == "+34912345678"


def test_respeta_el_codigo_de_pais_que_trae():
    assert normalizar("+57 300 123 4567").valor == "+573001234567"


def test_numero_extranjero_con_codigo_pero_sin_mas():
    assert normalizar("573001234567").valor == "+573001234567"


@pytest.mark.parametrize("texto", ["123", "3001234567", "999999999999999"])
def test_lo_que_no_se_puede_interpretar_queda_para_revisar(texto):
    telefono = normalizar(texto)
    assert telefono.revisar
    assert telefono.valor == "".join(c for c in texto if c.isdigit())


@pytest.mark.parametrize("texto", [None, "", "   ", "anónimo"])
def test_sin_digitos_no_hay_telefono(texto):
    assert normalizar(texto) is None
