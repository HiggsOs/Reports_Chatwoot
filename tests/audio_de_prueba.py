"""WAV sintéticos para las pruebas, sin depender de ffmpeg para crearlos."""

import io
import math
import struct
import wave


def wav(segundos: float = 2.0, canales: int = 1, frecuencia: int = 8000) -> bytes:
    """Un tono de 440 Hz; en estéreo, el canal derecho a 880 Hz."""
    memoria = io.BytesIO()
    with wave.open(memoria, "wb") as archivo:
        archivo.setnchannels(canales)
        archivo.setsampwidth(2)
        archivo.setframerate(frecuencia)
        muestras = []
        for i in range(int(segundos * frecuencia)):
            for canal in range(canales):
                tono = 440 * (canal + 1)
                muestras.append(int(8000 * math.sin(2 * math.pi * tono * i / frecuencia)))
        archivo.writeframes(struct.pack(f"<{len(muestras)}h", *muestras))
    return memoria.getvalue()
