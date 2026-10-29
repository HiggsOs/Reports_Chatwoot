"""WAV de CloudTalk → MP3, con ffprobe y ffmpeg.

Una llamada telefónica (8 kHz) en MP3 ocupa unas cuatro veces menos que en WAV
—más si el WAV es de mayor calidad— y se oye igual. Si la grabación es estéreo
(cada persona en un canal), el MP3 conserva los dos canales: separarlos es lo
que permite, al transcribir, saber con exactitud quién dijo qué.
"""

import json
import subprocess
import tempfile

from pydantic import BaseModel

BITRATE_MONO = "32k"
BITRATE_ESTEREO = "64k"
TIEMPO_LIMITE_SEGUNDOS = 120


class AudioInvalido(ValueError):
    """El archivo no se pudo leer como audio."""


class InfoAudio(BaseModel):
    canales: int
    duracion_s: float | None
    frecuencia_hz: int | None


def _ejecutar(comando: list[str], entrada: bytes) -> bytes:
    try:
        resultado = subprocess.run(
            comando,
            input=entrada,
            capture_output=True,
            timeout=TIEMPO_LIMITE_SEGUNDOS,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"Falta {comando[0]} en el sistema.") from error
    if resultado.returncode != 0:
        detalle = resultado.stderr.decode("utf-8", "replace").strip()[-300:]
        raise AudioInvalido(f"{comando[0]} no pudo procesar el audio: {detalle}")
    return resultado.stdout


def analizar(audio: bytes) -> InfoAudio:
    # Desde un archivo y no por tubería: por tubería ffprobe no sabe la duración.
    with tempfile.NamedTemporaryFile() as archivo:
        archivo.write(audio)
        archivo.flush()
        salida = _ejecutar(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=channels,sample_rate:format=duration",
                "-of", "json", archivo.name,
            ],
            b"",
        )
    datos = json.loads(salida or b"{}")
    pistas = datos.get("streams") or []
    if not pistas:
        raise AudioInvalido("El archivo no tiene una pista de audio.")
    pista = {**pistas[0], **(datos.get("format") or {})}

    def numero(clave, tipo):
        try:
            return tipo(pista.get(clave))
        except (TypeError, ValueError):
            return None

    return InfoAudio(
        canales=numero("channels", int) or 1,
        duracion_s=numero("duration", float),
        frecuencia_hz=numero("sample_rate", int),
    )


def a_mp3(audio: bytes, canales: int) -> bytes:
    estereo = canales >= 2
    return _ejecutar(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-ac", "2" if estereo else "1",
            "-b:a", BITRATE_ESTEREO if estereo else BITRATE_MONO,
            "-f", "mp3", "pipe:1",
        ],
        audio,
    )
