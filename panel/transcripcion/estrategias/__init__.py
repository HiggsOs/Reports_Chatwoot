"""Estrategias de transcripción. Importarlas aquí las registra.

El orden de importación es el orden en que aparecen en el panel: OpenAI
primero, porque es el proveedor por defecto.
"""

from panel.transcripcion.estrategias import openai  # noqa: F401, I001
from panel.transcripcion.estrategias import deepgram, falsa  # noqa: F401
