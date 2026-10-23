from datetime import date

import reporte_cloudtalk
from chatwoot import CacheMensajes
from reporte_cloudtalk import (
    COLUMNAS,
    SIN_GRABACION,
    SIN_TRANSCRIPCION,
    TRANSCRITA,
    construir_fila,
    escribir_csv,
    formatear_espera,
    generar_filas,
    nombre_agente,
    nombre_archivo,
    texto_transcripcion,
)

LLAMADA = {
    "Cdr": {
        "id": "27",
        "billsec": "30",
        "type": "incoming",
        "recorded": True,
        "talking_time": "21",
        "started_at": "2026-09-01T08:28:01.000Z",
    },
    "Agent": {"id": "1000", "firstname": "Tatiana", "lastname": "Velandia",
              "fullname": "Tatiana Velandia"},
}

TRANSCRIPCION = {
    "callId": 27,
    "segments": [
        {"start": 5.1, "end": 8.5, "caller": "caller1", "text": "Hola, necesito una grúa."},
        {"start": 1.5, "end": 4.5, "caller": "caller2", "text": "Buen día, servicio de grúa."},
        {"start": 9.0, "end": 9.5, "caller": "caller1", "text": "   "},
    ],
    "callers": [
        {"id": 5000, "type": "contact", "localIdentifier": "caller1"},
        {"id": 1000, "type": "agent", "localIdentifier": "caller2"},
    ],
    "language": "es",
}


class ClienteFalso:
    def __init__(self, llamadas, transcripciones):
        self.llamadas = llamadas
        self.transcripciones = transcripciones
        self.pedidas = []

    def listar_llamadas(self, desde, hasta):
        return self.llamadas

    def obtener_transcripcion(self, call_id):
        self.pedidas.append(call_id)
        return self.transcripciones.get(call_id)


def test_nombre_del_agente():
    assert nombre_agente(LLAMADA) == "Tatiana Velandia"
    assert nombre_agente({"Agent": {"firstname": "Ana", "lastname": "Gil"}}) == "Ana Gil"
    assert nombre_agente({"Cdr": {"user_id": "42"}}) == "Agente 42"


def test_dialogo_ordenado_y_con_hablantes():
    assert texto_transcripcion(TRANSCRIPCION, LLAMADA) == (
        "[Tatiana Velandia]: Buen día, servicio de grúa.\n"
        "[Cliente]: Hola, necesito una grúa."
    )


def test_un_segundo_agente_queda_identificado():
    transcripcion = {
        "segments": [{"start": 0, "caller": "caller3", "text": "Le transfiero."}],
        "callers": [{"id": 2000, "type": "agent", "localIdentifier": "caller3"}],
    }
    assert texto_transcripcion(transcripcion, LLAMADA) == "[Agente 2000]: Le transfiero."


def test_fila_completa():
    fila = construir_fila(LLAMADA, TRANSCRIPCION)

    assert tuple(fila) == COLUMNAS
    assert fila["call_id"] == "27"
    assert fila["fecha"].startswith("2026-09-01 03:28")
    assert fila["direccion"] == "entrante"
    assert fila["duracion_total"] == "21.00s"
    assert fila["estado"] == TRANSCRITA


def test_estado_sin_transcripcion_o_sin_grabacion():
    assert construir_fila(LLAMADA, None)["estado"] == SIN_TRANSCRIPCION
    sin_grabar = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "recorded": False}}
    assert construir_fila(sin_grabar, None)["estado"] == SIN_GRABACION


def test_no_pide_transcripcion_de_llamadas_sin_grabar():
    sin_grabar = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "28", "recorded": False}}
    cliente = ClienteFalso([LLAMADA, sin_grabar], {"27": TRANSCRIPCION})

    filas = generar_filas(cliente, None, None)

    assert cliente.pedidas == ["27"]
    assert len(filas) == 2


def test_usa_la_cache_y_no_guarda_las_faltantes(tmp_path):
    cache = CacheMensajes(tmp_path)
    otra = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "28"}}
    cliente = ClienteFalso([LLAMADA, otra], {"27": TRANSCRIPCION})

    generar_filas(cliente, None, None, cache=cache)
    generar_filas(cliente, None, None, cache=cache)

    # La 27 se pidió una sola vez; la 28, sin transcripción, se vuelve a pedir.
    assert cliente.pedidas == ["27", "28", "28"]
    assert cache.leer("28") is None


def test_avisa_el_avance():
    avances = []
    generar_filas(
        ClienteFalso([LLAMADA], {}), None, None,
        al_avanzar=lambda hechas, total, _: avances.append((hechas, total)),
    )
    assert avances == [(0, 1), (1, 1)]


def test_estima_con_el_ritmo_del_cliente_y_luego_con_el_medido(monkeypatch):
    llamadas = [
        {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": str(i)}} for i in range(4)
    ]
    cliente = ClienteFalso(llamadas, {})
    cliente.segundos_por_peticion = 1.0
    # Cada descarga tarda 3 s según el reloj: más lento que el ritmo nominal.
    reloj = iter([0.0, 3.0, 6.0, 9.0, 12.0])
    monkeypatch.setattr(reporte_cloudtalk.time, "monotonic", lambda: next(reloj))
    restantes = []

    generar_filas(cliente, None, None, al_avanzar=lambda h, t, r: restantes.append(r))

    # Antes de empezar: 4 pendientes a 1 s. Después: lo que falta a 3 s cada una.
    assert restantes == [4.0, 9.0, 6.0, 3.0, 0.0]


def test_las_que_estan_en_cache_no_suman_tiempo(tmp_path):
    cache = CacheMensajes(tmp_path)
    cache.guardar("27", TRANSCRIPCION)
    restantes = []

    generar_filas(
        ClienteFalso([LLAMADA], {}), None, None, cache=cache,
        al_avanzar=lambda h, t, r: restantes.append(r),
    )

    assert restantes == [0.0, 0.0]


def test_formatear_espera():
    assert formatear_espera(0) == ""
    assert formatear_espera(45) == "menos de 1 min"
    assert formatear_espera(61) == "unos 2 min"
    assert formatear_espera(3600) == "unas 1 h"
    assert formatear_espera(5000) == "unas 1 h 24 min"


def test_csv_con_bom_y_nombre_de_archivo():
    contenido = escribir_csv([construir_fila(LLAMADA, TRANSCRIPCION)])
    assert contenido.startswith(b"\xef\xbb\xbf")
    assert "Buen día" in contenido.decode("utf-8-sig")
    assert nombre_archivo(date(2026, 9, 1), date(2026, 9, 30)) == (
        "reporte-cloudtalk-2026-09-01-a-2026-09-30.csv"
    )


# --- Filtros ---------------------------------------------------------------

from reporte_cloudtalk import (  # noqa: E402
    Filtros,
    cumple_filtros,
    opciones_agentes,
    opciones_grupos,
    opciones_numeros,
)

LLAMADA_COMPLETA = {
    "Cdr": {
        "id": "30",
        "type": "outgoing",
        "recorded": True,
        "talking_time": "45",
        "user_id": "1000",
        "public_external": 573001234567,
        "started_at": "2026-09-01T08:28:01.000Z",
    },
    "Agent": {"id": "1000", "fullname": "Tatiana Velandia", "groups": ["Ventas", "Soporte"]},
    "CallNumber": {"id": "12345"},
    "Contact": {"name": "Grúas del Norte", "company": "Transportes ABC",
                "contact_numbers": [573109998877]},
}


def test_sin_filtros_entra_todo():
    assert cumple_filtros(LLAMADA_COMPLETA, Filtros())
    assert cumple_filtros({}, Filtros())


def test_filtra_por_agente():
    assert cumple_filtros(LLAMADA_COMPLETA, Filtros(agentes=frozenset({"1000", "7"})))
    assert not cumple_filtros(LLAMADA_COMPLETA, Filtros(agentes=frozenset({"7"})))


def test_filtra_por_grupo_sin_importar_mayusculas():
    assert cumple_filtros(LLAMADA_COMPLETA, Filtros(grupos=frozenset({"ventas"})))
    assert not cumple_filtros(LLAMADA_COMPLETA, Filtros(grupos=frozenset({"Cobranza"})))


def test_filtra_por_numero_de_la_empresa():
    assert cumple_filtros(LLAMADA_COMPLETA, Filtros(numeros=frozenset({"12345"})))
    assert not cumple_filtros(LLAMADA_COMPLETA, Filtros(numeros=frozenset({"1"})))


def test_filtra_por_direccion():
    assert cumple_filtros(LLAMADA_COMPLETA, Filtros(direcciones=frozenset({"outgoing"})))
    assert not cumple_filtros(LLAMADA_COMPLETA, Filtros(direcciones=frozenset({"incoming"})))


def test_filtra_por_duracion_minima():
    assert cumple_filtros(LLAMADA_COMPLETA, Filtros(duracion_minima=45))
    assert not cumple_filtros(LLAMADA_COMPLETA, Filtros(duracion_minima=46))


def test_busca_el_cliente_por_nombre_empresa_o_telefono():
    for busqueda in ("grúas", "ABC", "+57 300 123", "3109998877"):
        assert cumple_filtros(LLAMADA_COMPLETA, Filtros(contacto=busqueda)), busqueda
    assert not cumple_filtros(LLAMADA_COMPLETA, Filtros(contacto="Otra empresa"))
    # Muy pocos dígitos coincidirían con casi cualquier número.
    assert not cumple_filtros(LLAMADA_COMPLETA, Filtros(contacto="57"))


def test_solo_con_transcripcion_descarta_las_no_grabadas_y_las_sin_texto():
    sin_grabar = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "28", "recorded": False}}
    sin_texto = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "29"}}
    cliente = ClienteFalso([LLAMADA, sin_grabar, sin_texto], {"27": TRANSCRIPCION})

    filas = generar_filas(
        cliente, None, None, filtros=Filtros(solo_con_transcripcion=True)
    )

    assert [f["call_id"] for f in filas] == ["27"]
    # La no grabada ni se consultó.
    assert cliente.pedidas == ["27", "29"]


def test_los_filtros_evitan_pedir_transcripciones():
    otra = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "31"},
            "Agent": {"id": "2000", "fullname": "Otro"}}
    cliente = ClienteFalso([LLAMADA, otra], {})
    avances = []

    filas = generar_filas(
        cliente, None, None, filtros=Filtros(agentes=frozenset({"1000"})),
        al_avanzar=lambda h, t, r: avances.append(t),
    )

    assert [f["call_id"] for f in filas] == ["27"]
    assert cliente.pedidas == ["27"]
    assert set(avances) == {1}


def test_opciones_de_los_selectores():
    agentes = opciones_agentes([
        {"id": "2", "firstname": "Zoe", "lastname": "Ruiz", "extension": "1002"},
        {"id": "1", "firstname": "Ana", "lastname": "Gil"},
        {"id": "3", "email": "x@y.com"},
        {"firstname": "Sin id"},
    ])
    assert agentes == {"1": "Ana Gil", "2": "Zoe Ruiz (ext. 1002)", "3": "x@y.com"}

    numeros = opciones_numeros([
        {"id": "123", "internal_name": "Ventas", "caller_id_e164": 573001112233},
        {"id": "124", "caller_id_e164": "+573004445566"},
    ])
    assert numeros == {"124": "+573004445566", "123": "Ventas · +573001112233"}

    assert opciones_grupos(
        [{"internal_name": "soporte"}, {"internal_name": "Ventas"}, {"internal_name": ""}]
    ) == ["soporte", "Ventas"]


# --- Resumen y diagnóstico ---------------------------------------------------

from reporte_cloudtalk import Resumen, diagnosticar  # noqa: E402


def test_resumen_cuenta_cada_paso():
    sin_grabar = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "28", "recorded": False}}
    sin_texto = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "29"}}
    resumen = Resumen()

    generar_filas(
        ClienteFalso([LLAMADA, sin_grabar, sin_texto], {"27": TRANSCRIPCION}),
        None, None, filtros=Filtros(solo_con_transcripcion=True), resumen=resumen,
    )

    assert resumen == Resumen(
        en_rango=3, grabadas_en_rango=2, tras_filtros=2, consultadas=2,
        con_transcripcion=1,
    )
    assert diagnosticar(resumen) is None


def test_diagnostica_cuando_ninguna_grabada_tiene_transcripcion():
    resumen = Resumen()
    filas = generar_filas(
        ClienteFalso([LLAMADA], {}), None, None,
        filtros=Filtros(solo_con_transcripcion=True), resumen=resumen,
    )

    assert filas == []
    assert "Conversation Intelligence" in diagnosticar(resumen)


def test_diagnostica_cada_causa_de_un_reporte_vacio():
    assert "no devolvió llamadas" in diagnosticar(Resumen())
    assert "grabada" in diagnosticar(Resumen(en_rango=5))
    assert "filtros" in diagnosticar(Resumen(en_rango=5, grabadas_en_rango=5))
