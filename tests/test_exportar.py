import io
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from panel.exportar import a_excel


def test_excel_con_encabezado_fechas_y_texto_seguro():
    madrid = ZoneInfo("Europe/Madrid")
    contenido = a_excel(
        ["Id", "Fecha", "Duración (s)", "Texto"],
        [
            ["900", datetime(2026, 11, 3, 10, 0, tzinfo=madrid), 272, "=HYPERLINK(\"http://x\")"],
            ["901", None, None, "Agente: Hola\nCliente: Necesito una grúa\x07"],
        ],
        hoja="Llamadas",
    )
    hoja = load_workbook(io.BytesIO(contenido)).active
    assert hoja.title == "Llamadas"
    assert [c.value for c in hoja[1]] == ["Id", "Fecha", "Duración (s)", "Texto"]
    assert hoja["A1"].font.bold and hoja.freeze_panes == "A2" and hoja.auto_filter.ref == "A1:D3"

    # La fecha es una fecha de Excel, en la hora local que traía.
    assert hoja["B2"].value == datetime(2026, 11, 3, 10, 0) and hoja["B2"].number_format == "yyyy-mm-dd hh:mm"
    assert hoja["C2"].value == 272
    # Un texto que empieza con «=» queda como texto, no como fórmula.
    assert hoja["D2"].data_type == "s" and hoja["D2"].value == "=HYPERLINK(\"http://x\")"
    # Los caracteres que Excel no admite se quitan; el texto largo se ajusta.
    assert hoja["D3"].value == "Agente: Hola\nCliente: Necesito una grúa"
    assert hoja["D3"].alignment.wrap_text


def test_excel_sin_filas():
    hoja = load_workbook(io.BytesIO(a_excel(["Id"], []))).active
    assert [c.value for c in hoja[1]] == ["Id"] and hoja.max_row == 1
