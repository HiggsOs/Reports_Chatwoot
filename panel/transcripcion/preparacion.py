"""Preparación del audio antes de transcribir (Strategy elegida por una Factory).

CloudTalk solo garantiza WAV: cada grabación puede ser mono, estéreo real (un
canal por persona) o estéreo con el mismo audio en los dos canales. La fábrica
mira el archivo y elige el preparador; cada uno arma un `PlanTranscripcion`
que dice qué audios transcribir y qué capacidades conviene pedirle al
proveedor. Este paso y el de transcripción solo se cruzan por esas
capacidades.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from panel.audio import conversion
from panel.transcripcion.base import AudioPreparado

CanalAgente = Literal["izquierdo", "derecho"]
CANALES = {"izquierdo": 0, "derecho": 1}
MIME_MP3 = "audio/mpeg"


class PlanTranscripcion(BaseModel):
    model_config = ConfigDict(frozen=True)

    canales_audio: Literal["mono", "estereo", "estereo_duplicado"]
    partes: list[AudioPreparado]
    # Estéreo: cada canal se transcribe aparte y los segmentos se intercalan por
    # su hora, así que hacen falta marcas de tiempo.
    necesita_marcas: bool
    # Mono: sin separar hablantes, todo queda como «desconocido».
    prefiere_diarizacion: bool


class Preparador(Protocol):
    def preparar(self, mp3: bytes, nombre: str, duracion_s: float | None) -> PlanTranscripcion: ...


class Mono:
    def preparar(self, mp3, nombre, duracion_s):
        return PlanTranscripcion(
            canales_audio="mono",
            partes=[AudioPreparado(contenido=mp3, nombre_archivo=nombre, tipo_mime=MIME_MP3,
                                   duracion_s=duracion_s)],
            necesita_marcas=False,
            prefiere_diarizacion=True,
        )


class EstereoDuplicado:
    """Dos canales con el mismo audio: se pasa a mono (la mitad de tamaño) y se
    trata como mono."""

    def preparar(self, mp3, nombre, duracion_s):
        plan = Mono().preparar(conversion.a_mono(mp3), nombre, duracion_s)
        return plan.model_copy(update={"canales_audio": "estereo_duplicado"})


class EstereoPorCanal:
    """Un canal por persona: la atribución de hablantes es exacta."""

    def __init__(self, canal_agente: CanalAgente) -> None:
        self._agente = CANALES[canal_agente]

    def preparar(self, mp3, nombre, duracion_s):
        base = nombre.rsplit(".", 1)[0]
        partes = []
        for hablante, canal in (("agente", self._agente), ("cliente", 1 - self._agente)):
            partes.append(
                AudioPreparado(
                    contenido=conversion.extraer_canal(mp3, canal),
                    nombre_archivo=f"{base}-{hablante}.mp3",
                    tipo_mime=MIME_MP3,
                    duracion_s=duracion_s,
                    hablante=hablante,
                )
            )
        return PlanTranscripcion(
            canales_audio="estereo",
            partes=partes,
            necesita_marcas=True,
            prefiere_diarizacion=False,
        )


def elegir_preparador(mp3: bytes, canal_agente: CanalAgente) -> tuple[Preparador, float | None]:
    """El preparador que corresponde al archivo, y su duración."""
    info = conversion.analizar(mp3)
    if info.canales < 2:
        return Mono(), info.duracion_s
    if conversion.canales_iguales(mp3):
        return EstereoDuplicado(), info.duracion_s
    return EstereoPorCanal(canal_agente), info.duracion_s


def preparar(mp3: bytes, nombre: str, canal_agente: CanalAgente) -> PlanTranscripcion:
    preparador, duracion = elegir_preparador(mp3, canal_agente)
    return preparador.preparar(mp3, nombre, duracion)


def como_mono(plan: PlanTranscripcion, mp3: bytes, nombre: str) -> PlanTranscripcion:
    """Si ningún proveedor da marcas de tiempo, un estéreo se transcribe entero
    (mezclado) en vez de por canal: se pierde la atribución exacta, pero el
    diálogo queda en orden."""
    duracion = plan.partes[0].duracion_s if plan.partes else None
    mono = Mono().preparar(conversion.a_mono(mp3), nombre, duracion)
    return mono.model_copy(update={"canales_audio": plan.canales_audio})


def partir(audio: AudioPreparado, tamano_max: int) -> list[tuple[float, AudioPreparado]]:
    """Si el audio supera el tamaño que acepta el proveedor, lo parte en tramos
    del mismo largo. Devuelve (segundo de inicio, tramo)."""
    if len(audio.contenido) <= tamano_max or not audio.duracion_s:
        return [(0.0, audio)]
    tramos = -(-len(audio.contenido) // int(tamano_max * 0.9))  # con margen
    largo = audio.duracion_s / tramos
    resultado = []
    for indice in range(tramos):
        desde = indice * largo
        contenido = conversion.recortar(audio.contenido, desde, largo)
        resultado.append(
            (desde, audio.model_copy(update={"contenido": contenido, "duracion_s": largo}))
        )
    return resultado
