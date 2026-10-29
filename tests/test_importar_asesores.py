from pathlib import Path

import pytest

from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea
from panel.importar_asesores import importar_asesores_csv


def escribir_csv(directorio: Path, contenido: str) -> Path:
    ruta = directorio / "asesores.csv"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def mapa(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        return RepositorioPersonas(sesion).mapa_areas()


def test_sin_archivo_no_hace_nada(fabrica, tmp_path):
    assert importar_asesores_csv(tmp_path / "asesores.csv", fabrica) is None
    assert mapa(fabrica) == {}


def test_importa_y_deja_el_archivo_como_respaldo(fabrica, tmp_path):
    ruta = escribir_csv(
        tmp_path, "email_asesor,area\n Ana@E.com ,Comercial\nluis@e.com,RDC\n"
    )

    resultado = importar_asesores_csv(ruta, fabrica)

    assert resultado.importados == 2
    assert resultado.descartados == []
    assert mapa(fabrica) == {"ana@e.com": "Comercial", "luis@e.com": "RDC"}
    assert not ruta.exists()
    assert resultado.respaldo == tmp_path / "asesores.csv.migrado"
    assert resultado.respaldo.exists()


def test_descarta_las_filas_con_area_invalida(fabrica, tmp_path):
    ruta = escribir_csv(tmp_path, "email_asesor,area\nana@e.com,Ventas\nluis@e.com,RDC\n")

    resultado = importar_asesores_csv(ruta, fabrica)

    assert resultado.importados == 1
    assert resultado.descartados == ["ana@e.com (Ventas)"]
    assert mapa(fabrica) == {"luis@e.com": "RDC"}


def test_si_la_base_ya_tiene_asesores_no_los_pisa(fabrica, tmp_path):
    with unidad_de_trabajo(fabrica) as sesion:
        RepositorioPersonas(sesion).sincronizar_areas(
            [AsesorArea(correo="ana@e.com", area="RDC")]
        )
    ruta = escribir_csv(tmp_path, "email_asesor,area\nana@e.com,Comercial\n")

    resultado = importar_asesores_csv(ruta, fabrica)

    assert resultado.omitido_por_base_con_datos
    assert resultado.importados == 0
    assert mapa(fabrica) == {"ana@e.com": "RDC"}
    assert not ruta.exists()


def test_no_pisa_un_respaldo_anterior(fabrica, tmp_path):
    anterior = tmp_path / "asesores.csv.migrado"
    anterior.write_text("respaldo viejo", encoding="utf-8")
    ruta = escribir_csv(tmp_path, "email_asesor,area\nana@e.com,RDC\n")

    resultado = importar_asesores_csv(ruta, fabrica)

    assert anterior.read_text(encoding="utf-8") == "respaldo viejo"
    assert resultado.respaldo.name.startswith("asesores.csv.migrado.")
    assert resultado.respaldo.exists()


def test_si_falla_la_base_el_archivo_queda_para_reintentar(fabrica, tmp_path, monkeypatch):
    ruta = escribir_csv(tmp_path, "email_asesor,area\nana@e.com,RDC\n")

    def fallar(self, asesores):
        raise RuntimeError("se cayó la base")

    monkeypatch.setattr(RepositorioPersonas, "sincronizar_areas", fallar)
    with pytest.raises(RuntimeError):
        importar_asesores_csv(ruta, fabrica)

    assert ruta.exists()
