from pathlib import Path

from reporte import cargar_asesores, guardar_asesores, resolver_area


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
