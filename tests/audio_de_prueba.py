"""WAV sintéticos para las pruebas, sin depender de ffmpeg para crearlos."""

import io
import math
import struct
import wave


def wav(
    segundos: float = 2.0, canales: int = 1, frecuencia: int = 8000, duplicado: bool = False
) -> bytes:
    """Un tono de 440 Hz; en estéreo, el canal derecho a 880 Hz, o también a
    440 Hz si `duplicado` (el mismo audio en los dos canales)."""
    memoria = io.BytesIO()
    with wave.open(memoria, "wb") as archivo:
        archivo.setnchannels(canales)
        archivo.setsampwidth(2)
        archivo.setframerate(frecuencia)
        muestras = []
        for i in range(int(segundos * frecuencia)):
            for canal in range(canales):
                tono = 440 if duplicado else 440 * (canal + 1)
                muestras.append(int(8000 * math.sin(2 * math.pi * tono * i / frecuencia)))
        archivo.writeframes(struct.pack(f"<{len(muestras)}h", *muestras))
    return memoria.getvalue()
