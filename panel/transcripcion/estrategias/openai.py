"""Estrategia de OpenAI: `POST /v1/audio/transcriptions`.

Cada modelo devuelve otro formato, y esta clase lo traduce a la forma común
(patrón Adapter dentro de la estrategia):

- `diarized_json` (gpt-4o-transcribe-diarize): segmentos con hablante y tiempos.
- `verbose_json` (whisper-1): segmentos con tiempos, sin hablante.
- `json` (gpt-4o-transcribe, gpt-4o-mini-transcribe y los modelos que no se
  conocen): solo el texto.

Formatos y parámetros tomados de los tipos del SDK oficial de OpenAI (3.41.0).
OpenAI anunció el apagado de todos los modelos salvo `gpt-transcribe` para el
2027-02-26. Con un modelo nuevo, OPENAI_FORMATO_RESPUESTA indica qué formato
pedir sin tocar el código.
"""

import math
import time
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

import requests

from panel.transcripcion.base import (
    AudioPreparado,
    Capacidades,
    OpcionesTranscripcion,
    Segmento,
    Transcripcion,
    TranscripcionError,
    TranscripcionNoDisponible,
)
from panel.transcripcion.registro import registrar

URL_POR_DEFECTO = "https://api.openai.com/v1"
MODELO_POR_DEFECTO = "gpt-4o-transcribe-diarize"
TAMANO_MAXIMO_BYTES = 25 * 1024 * 1024
TIEMPO_LIMITE_SEGUNDOS = 600
INTENTOS_MAXIMOS = 3
ESPERA_BASE_SEGUNDOS = 2.0
ESPERA_MAXIMA_SEGUNDOS = 60.0

DIARIZADO, DETALLADO, SIMPLE = "diarized_json", "verbose_json", "json"
FORMATOS_POR_MODELO = {
    "gpt-4o-transcribe-diarize": DIARIZADO,
    "whisper-1": DETALLADO,
}
# Modelos que aceptan `prompt` (el vocabulario como contexto) y los que
# aceptan `keywords`. El diarizado no acepta ninguno de los dos.
CON_PROMPT = ("whisper-1", "gpt-4o-transcribe", "gpt-4o-mini-transcribe")
CON_KEYWORDS = ("gpt-transcribe",)


def _decimal(texto: str | None) -> Decimal | None:
    if not (texto or "").strip():
        return None
    try:
        return Decimal(texto.strip().replace(",", "."))
    except InvalidOperation as error:
        raise TranscripcionNoDisponible(
            f"OPENAI_PRECIO_MINUTO no es un número: {texto!r}"
        ) from error


def _capacidades(formato: str) -> Capacidades:
    return Capacidades(
        diarizacion=formato == DIARIZADO,
        marcas_de_tiempo=formato in (DIARIZADO, DETALLADO),
        tamano_max_bytes=TAMANO_MAXIMO_BYTES,
    )


@registrar
class EstrategiaOpenAI:
    nombre = "openai"
    titulo = "OpenAI"
    # Para la pantalla Transcripción: dónde va la clave y qué variables eligen
    # el modelo, el precio y el redondeo (ver registro.crear_modelo).
    variable_clave = "OPENAI_API_KEY"
    variables_modelo = ("OPENAI_MODELO_TRANSCRIPCION", "OPENAI_PRECIO_MINUTO", "OPENAI_REDONDEO")
    modelos_conocidos = {
        "gpt-4o-transcribe-diarize": _capacidades(DIARIZADO),
        "whisper-1": _capacidades(DETALLADO),
        "gpt-4o-transcribe": _capacidades(SIMPLE),
        "gpt-4o-mini-transcribe": _capacidades(SIMPLE),
    }

    def __init__(
        self,
        clave: str,
        modelo: str = MODELO_POR_DEFECTO,
        formato: str | None = None,
        precio_minuto: Decimal | None = None,
        url: str = URL_POR_DEFECTO,
        sesion: requests.Session | None = None,
        redondeo: str = "segundo",
    ) -> None:
        self._clave = clave
        self._modelo = modelo
        self._formato = formato or FORMATOS_POR_MODELO.get(modelo, SIMPLE)
        if self._formato not in (DIARIZADO, DETALLADO, SIMPLE):
            raise TranscripcionNoDisponible(
                f"OPENAI_FORMATO_RESPUESTA debe ser {DIARIZADO}, {DETALLADO} o {SIMPLE}."
            )
        self._precio = precio_minuto
        # «minuto»: el proveedor cobra cada audio redondeado al minuto siguiente.
        self._redondeo_minuto = redondeo == "minuto"
        self._url = url.rstrip("/")
        self._sesion = sesion or requests.Session()

    @classmethod
    def desde_config(cls, valores: Mapping[str, str]) -> "EstrategiaOpenAI":
        clave = (valores.get("OPENAI_API_KEY") or "").strip()
        if not clave:
            raise TranscripcionNoDisponible("Falta OPENAI_API_KEY.")
        return cls(
            clave=clave,
            modelo=(valores.get("OPENAI_MODELO_TRANSCRIPCION") or MODELO_POR_DEFECTO).strip(),
            formato=(valores.get("OPENAI_FORMATO_RESPUESTA") or "").strip() or None,
            precio_minuto=_decimal(valores.get("OPENAI_PRECIO_MINUTO")),
            url=(valores.get("OPENAI_BASE_URL") or URL_POR_DEFECTO).strip(),
            redondeo=(valores.get("OPENAI_REDONDEO") or "segundo").strip(),
        )

    @classmethod
    def probar_clave(cls, valores: Mapping[str, str]) -> str:
        """Pide la lista de modelos: no transcribe nada ni cuesta."""
        clave = (valores.get("OPENAI_API_KEY") or "").strip()
        if not clave:
            raise TranscripcionNoDisponible("Falta la clave de OpenAI.")
        url = (valores.get("OPENAI_BASE_URL") or URL_POR_DEFECTO).strip().rstrip("/")
        try:
            respuesta = requests.get(
                f"{url}/models", headers={"Authorization": f"Bearer {clave}"}, timeout=20
            )
        except requests.RequestException as error:
            raise TranscripcionError(f"No se pudo conectar con OpenAI: {error}") from error
        if respuesta.status_code in (401, 403):
            raise TranscripcionError("OpenAI rechazó la clave.")
        if respuesta.status_code >= 400:
            raise TranscripcionError(f"OpenAI respondió {respuesta.status_code}.")
        modelos = {m.get("id") for m in respuesta.json().get("data", [])}
        conocidos = sorted(m for m in cls.modelos_conocidos if m in modelos)
        return "Clave válida. Modelos de transcripción disponibles: " + (", ".join(conocidos) or "ninguno conocido")

    @property
    def modelo(self) -> str:
        return self._modelo

    @property
    def capacidades(self) -> Capacidades:
        return _capacidades(self._formato)

    def costo_estimado(self, duracion_s: float | None) -> Decimal | None:
        if self._precio is None or duracion_s is None:
            return None
        minutos = Decimal(str(duracion_s)) / 60
        if self._redondeo_minuto:
            minutos = Decimal(math.ceil(minutos))
        return (self._precio * minutos).quantize(Decimal("0.0001"))

    # --- Petición ------------------------------------------------------------

    def _campos(self, opciones: OpcionesTranscripcion) -> list[tuple[str, str]]:
        campos = [
            ("model", self._modelo),
            ("response_format", self._formato),
            ("language", opciones.idioma),
        ]
        if self._formato == DIARIZADO:
            # Obligatorio para audios de más de 30 segundos.
            campos.append(("chunking_strategy", "auto"))
        if opciones.vocabulario:
            if self._modelo in CON_KEYWORDS:
                campos += [("keywords[]", palabra) for palabra in opciones.vocabulario]
            elif self._modelo in CON_PROMPT:
                campos.append(("prompt", "Vocabulario: " + ", ".join(opciones.vocabulario)))
        return campos

    def _enviar(self, audio: AudioPreparado, opciones: OpcionesTranscripcion) -> dict:
        ultimo_error = ""
        for intento in range(INTENTOS_MAXIMOS):
            try:
                respuesta = self._sesion.post(
                    f"{self._url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self._clave}"},
                    data=self._campos(opciones),
                    files={"file": (audio.nombre_archivo, audio.contenido, audio.tipo_mime)},
                    timeout=TIEMPO_LIMITE_SEGUNDOS,
                )
            except requests.RequestException as error:
                ultimo_error = str(error)
                time.sleep(ESPERA_BASE_SEGUNDOS * (2**intento))
                continue

            if respuesta.status_code in (401, 403):
                raise TranscripcionError(
                    "OpenAI rechazó la clave. Revise OPENAI_API_KEY y que la cuenta "
                    "tenga acceso al modelo."
                )
            if respuesta.status_code < 400:
                return respuesta.json()
            if respuesta.status_code == 429 or respuesta.status_code >= 500:
                ultimo_error = f"HTTP {respuesta.status_code}: {respuesta.text[:200]}"
                time.sleep(self._espera(respuesta, intento))
                continue
            raise TranscripcionError(
                f"OpenAI respondió {respuesta.status_code}: {respuesta.text[:300]}"
            )
        raise TranscripcionError(
            f"OpenAI no respondió tras {INTENTOS_MAXIMOS} intentos ({ultimo_error})."
        )

    @staticmethod
    def _espera(respuesta: requests.Response, intento: int) -> float:
        try:
            espera = float(respuesta.headers.get("Retry-After", ""))
        except ValueError:
            espera = ESPERA_BASE_SEGUNDOS * (2**intento)
        return max(0.0, min(espera, ESPERA_MAXIMA_SEGUNDOS))

    # --- Traducción a la forma común -----------------------------------------

    def transcribir(self, audio: AudioPreparado, opciones: OpcionesTranscripcion) -> Transcripcion:
        if len(audio.contenido) > TAMANO_MAXIMO_BYTES:
            raise TranscripcionError("El audio supera los 25 MB que acepta OpenAI.")
        datos = self._enviar(audio, opciones)
        segmentos = self._segmentos(datos, audio)
        duracion = _numero(datos.get("duration"))
        if duracion is None:
            uso = datos.get("usage") or {}
            duracion = _numero(uso.get("seconds")) if uso.get("type") == "duration" else None
        duracion = duracion if duracion is not None else audio.duracion_s
        return Transcripcion(
            proveedor=self.nombre,
            modelo=self._modelo,
            idioma=datos.get("language") or opciones.idioma,
            segmentos=segmentos,
            duracion_audio=duracion,
            costo_estimado=self.costo_estimado(duracion),
        )

    def _segmentos(self, datos: dict, audio: AudioPreparado) -> list[Segmento]:
        hablante = audio.hablante or "desconocido"
        crudos = datos.get("segments") or []
        if self._formato in (DIARIZADO, DETALLADO) and crudos:
            segmentos = []
            for crudo in crudos:
                texto = (crudo.get("text") or "").strip()
                if not texto:
                    continue
                etiqueta = crudo.get("speaker") if audio.hablante is None else None
                segmentos.append(
                    Segmento(
                        hablante=hablante,
                        etiqueta=str(etiqueta) if etiqueta is not None else None,
                        inicio=_numero(crudo.get("start")),
                        fin=_numero(crudo.get("end")),
                        texto=texto,
                    )
                )
            return segmentos
        texto = (datos.get("text") or "").strip()
        return [Segmento(hablante=hablante, inicio=None, fin=None, texto=texto)] if texto else []


def _numero(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None
