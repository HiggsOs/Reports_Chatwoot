from datetime import datetime
from pathlib import Path

from reporte import (
    TZ,
    a_fecha_local,
    cargar_asesores,
    detectar_cierre,
    detectar_direccion,
    guardar_asesores,
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
