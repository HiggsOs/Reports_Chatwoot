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


def _ejecutar(comando: list[str], entrada: bytes, salida_de_error: bool = False) -> bytes:
    """Corre el comando con el audio por la entrada. Devuelve la salida, o la
    salida de error si `salida_de_error` (ahí escriben sus mediciones los
    filtros de ffmpeg)."""
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
    return resultado.stderr if salida_de_error else resultado.stdout


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


# Por debajo de este volumen, la diferencia entre los dos canales es silencio:
# es un «estéreo» con el mismo audio en ambos lados.
UMBRAL_CANALES_IGUALES_DB = -40.0


def canales_iguales(audio: bytes) -> bool:
    """Si los dos canales de un estéreo tienen el mismo audio.

    Mide el volumen máximo de la resta de los canales: si es silencio, son
    iguales.
    """
    errores = _ejecutar(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", "pipe:0",
            "-af", "pan=mono|c0=c0-c1,volumedetect", "-f", "null", "-",
        ],
        audio,
        salida_de_error=True,
    ).decode("utf-8", "replace")
    for linea in errores.splitlines():
        if "max_volume:" in linea:
            valor = linea.split("max_volume:")[1].strip().split()[0]
            return valor == "-inf" or float(valor) < UMBRAL_CANALES_IGUALES_DB
    return False


def extraer_canal(audio: bytes, canal: int) -> bytes:
    """Un canal (0 = izquierdo, 1 = derecho) como MP3 mono."""
    return _ejecutar(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-af", f"pan=mono|c0=c{canal}", "-b:a", BITRATE_MONO, "-f", "mp3", "pipe:1",
        ],
        audio,
    )


def a_mono(audio: bytes) -> bytes:
    return a_mp3(audio, canales=1)


def recortar(audio: bytes, desde_s: float, duracion_s: float) -> bytes:
    """Un tramo del MP3, sin volver a codificarlo."""
    return _ejecutar(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{desde_s:.3f}",
            "-t", f"{duracion_s:.3f}", "-i", "pipe:0", "-c", "copy", "-f", "mp3", "pipe:1",
        ],
        audio,
    )
