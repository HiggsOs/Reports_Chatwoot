from datetime import date, datetime
from pathlib import Path

from reporte import (
    COLUMNAS,
    TZ,
    a_fecha_local,
    cargar_asesores,
    construir_fila,
    detectar_cierre,
    detectar_direccion,
    escribir_csv,
    generar_filas,
    guardar_asesores,
    nombre_archivo,
    resolver_area,
    traducir_estado,
)


def test_archivo_inexistente_da_mapeo_vacio(tmp_path: Path):
    assert cargar_asesores(tmp_path / "no-existe.csv") == {}


def test_carga_normaliza_correos_y_espacios(tmp_path: Path):
    archivo = tmp_path / "asesores.csv"
    archivo.write_text(
        "email_asesor,area\n  Ana@Empresa.com , Comercial \nluis@empresa.com,RDC\n",
        encoding="utf-8",
    )
    assert cargar_asesores(archivo) == {
        "ana@empresa.com": "Comercial",
        "luis@empresa.com": "RDC",
    }


def test_ida_y_vuelta_de_guardado(tmp_path: Path):
    archivo = tmp_path / "sub" / "asesores.csv"
    mapeo = {"ana@empresa.com": "Comercial", "luis@empresa.com": "RDC"}
    guardar_asesores(archivo, mapeo)
    assert cargar_asesores(archivo) == mapeo


def test_guardar_ordena_por_correo(tmp_path: Path):
    archivo = tmp_path / "asesores.csv"
    guardar_asesores(archivo, {"zoe@e.com": "RDC", "ana@e.com": "Comercial"})
    lineas = archivo.read_text(encoding="utf-8").splitlines()
    assert lineas[1].startswith("ana@e.com")


def test_resolver_area_encuentra_al_asesor():
    assert resolver_area("Ana@Empresa.com", {"ana@empresa.com": "RDC"}) == "RDC"


def test_asesor_sin_mapear():
    assert resolver_area("nuevo@empresa.com", {}) == "SIN_MAPEAR"


def test_conversacion_sin_asesor_asignado():
    assert resolver_area(None, {"ana@empresa.com": "RDC"}) == "SIN_ASIGNAR"
    assert resolver_area("", {}) == "SIN_ASIGNAR"


# 2026-09-05 10:00 en Bogotá
EPOCH_CREACION = int(datetime(2026, 9, 5, 10, 0, tzinfo=TZ).timestamp())
EPOCH_CIERRE = int(datetime(2026, 9, 5, 14, 30, tzinfo=TZ).timestamp())


def mensaje(id_, tipo, contenido="", creado=EPOCH_CREACION):
    return {"id": id_, "message_type": tipo, "content": contenido, "created_at": creado}


DESDE_FECHA = datetime(2026, 9, 1, 0, 0, tzinfo=TZ)
HASTA_FECHA = datetime(2026, 9, 30, 23, 59, tzinfo=TZ)


def test_direccion_entrante():
    mensajes = [mensaje(1, 0, "hola"), mensaje(2, 1, "buenas")]
    assert detectar_direccion(mensajes) == "Entrante"


def test_direccion_saliente():
    mensajes = [mensaje(1, 1, "le escribimos"), mensaje(2, 0, "gracias")]
    assert detectar_direccion(mensajes) == "Saliente"


def test_direccion_ignora_actividades_previas():
    mensajes = [mensaje(1, 2, "Conversación asignada"), mensaje(2, 0, "hola")]
    assert detectar_direccion(mensajes) == "Entrante"


def test_direccion_indeterminada_sin_mensajes():
    assert detectar_direccion([]) == "Indeterminado"
    assert detectar_direccion([mensaje(1, 2, "actividad")]) == "Indeterminado"


def test_cierre_desde_actividad_en_espanol():
    conversacion = {"status": "resolved", "last_activity_at": EPOCH_CIERRE + 9999}
    mensajes = [
        mensaje(1, 0, "hola"),
        mensaje(2, 2, "Ana marcó la conversación como resuelta", EPOCH_CIERRE),
    ]
    fecha, aproximado = detectar_cierre(conversacion, mensajes)
    assert fecha == datetime.fromtimestamp(EPOCH_CIERRE, TZ)
    assert aproximado is False


def test_cierre_desde_actividad_en_ingles():
    conversacion = {"status": "resolved", "last_activity_at": EPOCH_CIERRE + 9999}
    mensajes = [mensaje(2, 2, "Conversation was marked resolved by Ana", EPOCH_CIERRE)]
    fecha, aproximado = detectar_cierre(conversacion, mensajes)
    assert fecha == datetime.fromtimestamp(EPOCH_CIERRE, TZ)
    assert aproximado is False


def test_cierre_toma_la_resolucion_mas_reciente_si_se_reabrio():
    posterior = EPOCH_CIERRE + 86400
    conversacion = {"status": "resolved", "last_activity_at": posterior}
    mensajes = [
        mensaje(2, 2, "marcó la conversación como resuelta", EPOCH_CIERRE),
        mensaje(3, 2, "reabrió la conversación", EPOCH_CIERRE + 100),
        mensaje(4, 2, "marcó la conversación como resuelta", posterior),
    ]
    fecha, aproximado = detectar_cierre(conversacion, mensajes)
    assert fecha == datetime.fromtimestamp(posterior, TZ)
    assert aproximado is False


def test_cierre_aproximado_cuando_no_hay_actividad_reconocible():
    conversacion = {"status": "resolved", "last_activity_at": EPOCH_CIERRE}
    mensajes = [mensaje(1, 0, "hola")]
    fecha, aproximado = detectar_cierre(conversacion, mensajes)
    assert fecha == datetime.fromtimestamp(EPOCH_CIERRE, TZ)
    assert aproximado is True


def test_sin_cierre_si_la_conversacion_sigue_abierta():
    conversacion = {"status": "open", "last_activity_at": EPOCH_CIERRE}
    assert detectar_cierre(conversacion, []) == (None, False)


def test_traduccion_de_estados():
    assert traducir_estado("open") == "abierta"
    assert traducir_estado("pending") == "pendiente"
    assert traducir_estado("resolved") == "resuelta"
    assert traducir_estado("snoozed") == "pospuesta"
    assert traducir_estado("otro") == "otro"


def test_conversion_de_epoch_a_hora_local():
    assert a_fecha_local(None) is None
    assert a_fecha_local(EPOCH_CREACION).hour == 10


MAPEO = {"ana@empresa.com": "Comercial", "luis@empresa.com": "RDC"}
INBOXES = {14: "Gruas Asistencia 24", 15: "Gruas Asistencia"}


def conversacion(**cambios):
    base = {
        "id": 101,
        "status": "resolved",
        "created_at": EPOCH_CREACION,
        "last_activity_at": EPOCH_CIERRE,
        "labels": ["cotizacion", "whatsapp"],
        "inbox_id": 14,
        "meta": {"assignee": {"name": "Ana Pérez", "email": "Ana@Empresa.com"}},
    }
    base.update(cambios)
    return base


MENSAJES = [
    mensaje(1, 0, "hola"),
    mensaje(2, 2, "Ana marcó la conversación como resuelta", EPOCH_CIERRE),
]


def test_fila_completa():
    fila = construir_fila(conversacion(), MENSAJES, MAPEO, INBOXES)
    assert fila["conversacion_id"] == "101"
    assert fila["asesor"] == "Ana Pérez"
    assert fila["email_asesor"] == "Ana@Empresa.com"
    assert fila["area"] == "Comercial"
    assert fila["fecha_creacion"] == "2026-09-05 10:00"
    assert fila["canal"] == "Gruas Asistencia 24"
    assert fila["etiquetas"] == "cotizacion;whatsapp"
    assert fila["direccion"] == "Entrante"
    assert fila["estado"] == "resuelta"
    assert fila["fecha_cierre"] == "2026-09-05 14:30"
    assert fila["tiempo_resolucion_horas"] == "4.5"
    assert fila["cierre_aproximado"] == ""


def test_fila_tiene_exactamente_las_columnas_definidas():
    assert set(construir_fila(conversacion(), MENSAJES, MAPEO)) == set(COLUMNAS)


def test_fila_de_conversacion_abierta():
    fila = construir_fila(conversacion(status="open"), MENSAJES, MAPEO)
    assert fila["estado"] == "abierta"
    assert fila["fecha_cierre"] == ""
    assert fila["tiempo_resolucion_horas"] == ""


def test_fila_sin_asesor_asignado():
    fila = construir_fila(conversacion(meta={}), MENSAJES, MAPEO)
    assert fila["asesor"] == ""
    assert fila["email_asesor"] == ""
    assert fila["area"] == "SIN_ASIGNAR"


def test_fila_con_asesor_sin_mapear():
    conv = conversacion(meta={"assignee": {"name": "Nuevo", "email": "n@empresa.com"}})
    assert construir_fila(conv, MENSAJES, MAPEO)["area"] == "SIN_MAPEAR"


def test_fila_sin_etiquetas():
    assert construir_fila(conversacion(labels=[]), MENSAJES, MAPEO)["etiquetas"] == ""


def test_fila_marca_el_cierre_aproximado():
    fila = construir_fila(conversacion(), [mensaje(1, 0, "hola")], MAPEO)
    assert fila["cierre_aproximado"] == "Sí"


def test_csv_lleva_bom_y_encabezados_en_espanol():
    contenido = escribir_csv([construir_fila(conversacion(), MENSAJES, MAPEO)])
    assert contenido.startswith(b"\xef\xbb\xbf")
    texto = contenido.decode("utf-8-sig")
    assert texto.splitlines()[0] == ",".join(COLUMNAS)
    assert "Ana Pérez" in texto


def test_csv_vacio_conserva_los_encabezados():
    texto = escribir_csv([]).decode("utf-8-sig")
    assert texto.strip() == ",".join(COLUMNAS)


def test_nombre_del_archivo():
    assert (
        nombre_archivo(date(2026, 9, 1), date(2026, 9, 30))
        == "reporte-chatwoot-2026-09-01-a-2026-09-30.csv"
    )


class ClienteFalso:
    def __init__(self, conversaciones, mensajes_por_id, inboxes=None):
        self.conversaciones = conversaciones
        self.mensajes_por_id = mensajes_por_id
        self.inboxes = inboxes if inboxes is not None else INBOXES
        self.pedidos = []

    def listar_conversaciones(self, desde, hasta):
        return self.conversaciones

    def listar_inboxes(self):
        return self.inboxes

    def listar_mensajes(self, conversacion_id):
        self.pedidos.append(conversacion_id)
        return self.mensajes_por_id[conversacion_id]


def test_generar_filas_recorre_todas_las_conversaciones():
    cliente = ClienteFalso([conversacion(), conversacion(id=102)], {101: MENSAJES, 102: MENSAJES})
    filas = generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO)
    assert [f["conversacion_id"] for f in filas] == ["101", "102"]


def test_generar_filas_informa_el_progreso():
    cliente = ClienteFalso([conversacion(), conversacion(id=102)], {101: MENSAJES, 102: MENSAJES})
    avances = []
    generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO, al_avanzar=lambda h, t: avances.append((h, t)))
    assert avances == [(1, 2), (2, 2)]


def test_generar_filas_usa_la_cache_de_conversaciones_resueltas(tmp_path: Path):
    from chatwoot import CacheMensajes

    cache = CacheMensajes(tmp_path)
    cache.guardar(101, MENSAJES)
    cliente = ClienteFalso([conversacion()], {})
    filas = generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO, cache=cache)
    assert cliente.pedidos == []
    assert filas[0]["direccion"] == "Entrante"


def test_generar_filas_no_cachea_conversaciones_abiertas(tmp_path: Path):
    from chatwoot import CacheMensajes

    cache = CacheMensajes(tmp_path)
    cliente = ClienteFalso([conversacion(status="open")], {101: MENSAJES})
    generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO, cache=cache)
    assert cache.leer(101) is None


def test_canal_usa_el_nombre_del_inbox():
    fila = construir_fila(conversacion(inbox_id=15), MENSAJES, MAPEO, INBOXES)
    assert fila["canal"] == "Gruas Asistencia"


def test_canal_de_un_inbox_desconocido_muestra_el_id():
    """Un inbox creado después de consultar la lista no debe romper el reporte."""
    fila = construir_fila(conversacion(inbox_id=99), MENSAJES, MAPEO, INBOXES)
    assert fila["canal"] == "inbox 99"


def test_conversacion_sin_inbox():
    fila = construir_fila(conversacion(inbox_id=None), MENSAJES, MAPEO, INBOXES)
    assert fila["canal"] == "SIN_CANAL"


def test_generar_filas_consulta_los_inboxes_una_sola_vez():
    cliente = ClienteFalso([conversacion(), conversacion(id=102)], {101: MENSAJES, 102: MENSAJES})
    filas = generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO)
    assert [f["canal"] for f in filas] == ["Gruas Asistencia 24", "Gruas Asistencia 24"]
