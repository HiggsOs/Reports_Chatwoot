from panel.transcripcion.base import Segmento
from panel.transcripcion.hablantes import (
    FRASES_AGENTE_POR_DEFECTO,
    aplicar_roles,
    identificar_agente,
    normalizar,
    roles_para,
)


def seg(etiqueta, texto, hablante="desconocido"):
    return Segmento(hablante=hablante, etiqueta=etiqueta, inicio=None, fin=None, texto=texto)


def test_normalizar():
    assert normalizar("¡Buen día, GRÚA Privada!") == "buen dia grua privada"


def test_el_agente_es_el_que_dice_el_saludo_aunque_no_hable_primero():
    segmentos = [seg("A", "¿Aló?"), seg("B", "Buen día, Grúas Privadas, le atiende Ana."), seg("A", "Necesito una grúa.")]
    sugerencia = identificar_agente(segmentos, FRASES_AGENTE_POR_DEFECTO)
    assert sugerencia.etiqueta == "B" and sugerencia.frase == "Buen día, Grúas Privadas, le atiende Ana."
    resueltos = aplicar_roles(segmentos, roles_para(segmentos, "B"))
    assert [s.hablante for s in resueltos] == ["cliente", "agente", "cliente"]


def test_si_los_dos_dicen_frases_gana_el_que_dice_mas():
    segmentos = [
        seg("A", "Hola, ¿es la grúa privada?"),
        seg("B", "Sí, servicio de grúa, le habla Luis, ¿en qué le puedo ayudar?"),
    ]
    assert identificar_agente(segmentos, FRASES_AGENTE_POR_DEFECTO).etiqueta == "B"
    # Empate: el que lo dijo primero.
    empate = [seg("A", "Servicio de grúa, buen día."), seg("B", "¿Es grúa privada?")]
    assert identificar_agente(empate, FRASES_AGENTE_POR_DEFECTO).etiqueta == "A"


def test_sin_saber_no_adivina():
    # Una sola voz: el modelo no separó; no hay a quién asignar.
    assert identificar_agente([seg("A", "Servicio de grúa"), seg("A", "Necesito una grúa")], FRASES_AGENTE_POR_DEFECTO) is None
    # Nadie dice una frase del agente.
    assert identificar_agente([seg("A", "Hola"), seg("B", "Buenas")], FRASES_AGENTE_POR_DEFECTO) is None
    # «grúa» suelta no alcanza: la dice también el cliente.
    assert identificar_agente([seg("A", "Hola"), seg("B", "Necesito una grúa")], FRASES_AGENTE_POR_DEFECTO) is None
    # Las voces ya resueltas no se tocan.
    resueltas = [seg("A", "Servicio de grúa", "agente"), seg("B", "Hola", "cliente")]
    assert identificar_agente(resueltas, FRASES_AGENTE_POR_DEFECTO) is None
