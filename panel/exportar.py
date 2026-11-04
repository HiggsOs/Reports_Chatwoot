"""Descargas en Excel (.xlsx): el mismo contenido que los CSV, listo para usar.

- Encabezado en negrita, fijo al bajar y con filtros.
- Fechas como fechas de Excel (en hora de la zona de operación), números como
  números.
- Las columnas de texto largo (transcripción, chat) quedan con ajuste de línea.
- Un texto que empieza con «=» (un mensaje de chat, por ejemplo) queda como
  texto: nunca se convierte en una fórmula.
"""

import io
from collections.abc import Iterable, Sequence
from datetime import datetime

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORMATO_FECHA = "yyyy-mm-dd hh:mm"
ANCHO_MAXIMO = 60
# Un texto más largo que esto se muestra con ajuste de línea.
TEXTO_LARGO = 80
FONDO_ENCABEZADO = PatternFill("solid", fgColor="DDEBF7")


def _valor(valor):
    if isinstance(valor, datetime):
        # Excel no guarda zona horaria: va la hora local que ya trae.
        return valor.replace(tzinfo=None)
    if isinstance(valor, str):
        return ILLEGAL_CHARACTERS_RE.sub("", valor)
    return valor


def a_excel(encabezados: Sequence[str], filas: Iterable[Sequence], hoja: str = "Datos") -> bytes:
    """Un libro con una hoja: `encabezados` y una fila por elemento de `filas`."""
    libro = Workbook()
    datos = libro.active
    datos.title = hoja[:31]
    datos.append(list(encabezados))
    anchos = [len(str(e)) for e in encabezados]
    largos = [False] * len(encabezados)
    for fila in filas:
        datos.append([_valor(v) for v in fila])
        for i, celda in enumerate(datos[datos.max_row]):
            if celda.data_type == "f":
                celda.data_type = "s"  # «=algo» es texto, no una fórmula
            if isinstance(celda.value, datetime):
                celda.number_format = FORMATO_FECHA
                anchos[i] = max(anchos[i], 16)
            elif celda.value is not None:
                texto = str(celda.value)
                anchos[i] = max(anchos[i], min(max(len(linea) for linea in texto.split("\n")), ANCHO_MAXIMO))
                largos[i] = largos[i] or len(texto) > TEXTO_LARGO or "\n" in texto

    for celda in datos[1]:
        celda.font = Font(bold=True)
        celda.fill = FONDO_ENCABEZADO
    for i, ancho in enumerate(anchos, start=1):
        letra = get_column_letter(i)
        datos.column_dimensions[letra].width = min(ancho + 2, ANCHO_MAXIMO + 2)
        if largos[i - 1]:
            for (celda,) in datos.iter_rows(min_row=2, min_col=i, max_col=i):
                celda.alignment = Alignment(wrap_text=True, vertical="top")
    datos.freeze_panes = "A2"
    if datos.max_row > 1:
        datos.auto_filter.ref = datos.dimensions

    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()
