"""Cliente HTTP de la API de CloudTalk."""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

BASE_URL_POR_DEFECTO = "https://my.cloudtalk.io/api"
# Las transcripciones son de Conversation Intelligence, que vive en otro
# servidor y no envuelve la respuesta en `responseData`.
AI_BASE_URL_POR_DEFECTO = "https://api.cloudtalk.io/v1"

# Errores de red o del servidor.
INTENTOS_MAXIMOS = 5
ESPERA_BASE_SEGUNDOS = 1.0
TIEMPO_LIMITE_SEGUNDOS = 60

# La cuenta admite 60 peticiones por minuto. Se espacian de antemano para no
# llegar al 429; si aun así llega (otra integración usa la misma clave, o las
# transcripciones tienen un límite propio), el intervalo se alarga solo.
INTERVALO_MINIMO_SEGUNDOS = 1.0
INTERVALO_MAXIMO_SEGUNDOS = 6.0
FACTOR_FRENADO = 1.5

# Ante un 429 sin Retry-After se espera la ventana completa del límite. Se
# tolera hasta media hora de pausas por petición antes de rendirse, para no
# tirar a la basura un reporte largo por un límite pasajero.
INTENTOS_MAXIMOS_LIMITE = 30
ESPERA_LIMITE_SEGUNDOS = 60.0
ESPERA_LIMITE_MAXIMA_SEGUNDOS = 300.0

# El historial de llamadas admite como máximo 1000 filas por página.
TAMANO_PAGINA_LLAMADAS = 1000
TAMANO_PAGINA_SEGMENTOS = 500

# Tope de seguridad: sin él, una API que ignorara la página dejaría el reporte
# pidiendo páginas para siempre.
PAGINAS_MAXIMAS = 200

FORMATO_FECHA_FILTRO = "%Y-%m-%d %H:%M:%S"

# La documentación no dice en qué zona horaria interpreta el filtro. Se pide un
# día de más por cada lado y el recorte fino se hace con `started_at`, que sí
# viene en UTC.
MARGEN_FILTRO = timedelta(days=1)


def _a_texto_utc(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime(FORMATO_FECHA_FILTRO)


def a_fecha_utc(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        momento = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento


def _dentro_del_rango(llamada: dict, desde: datetime, hasta: datetime) -> bool:
    inicio = a_fecha_utc((llamada.get("Cdr") or {}).get("started_at"))
    return inicio is not None and desde <= inicio <= hasta


def fue_grabada(llamada: dict) -> bool:
    """Sin grabación no hay transcripción; la API devuelve el valor como
    booleano o como texto según la cuenta."""
    valor = (llamada.get("Cdr") or {}).get("recorded")
    if isinstance(valor, str):
        return valor.strip().lower() in ("1", "true")
    return bool(valor)


class CloudTalkError(Exception):
    """Falló la comunicación con CloudTalk."""


class CloudTalkAuthError(CloudTalkError):
    """Las credenciales fueron rechazadas, o falta Conversation Intelligence."""


class ClienteCloudTalk:
    def __init__(
        self,
        key_id: str,
        key_secret: str,
        base_url: str = BASE_URL_POR_DEFECTO,
        ai_base_url: str = AI_BASE_URL_POR_DEFECTO,
        sesion: requests.Session | None = None,
        al_esperar=None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._base_ai = ai_base_url.rstrip("/")
        self._sesion = sesion or requests.Session()
        self._sesion.auth = (key_id, key_secret)
        self._al_esperar = al_esperar
        self._intervalo = INTERVALO_MINIMO_SEGUNDOS
        self._ultima_peticion: float | None = None

    @property
    def segundos_por_peticion(self) -> float:
        """Ritmo actual entre peticiones; sirve para estimar cuánto falta."""
        return self._intervalo

    def _respetar_limite(self) -> None:
        if self._ultima_peticion is not None:
            faltante = self._intervalo - (time.monotonic() - self._ultima_peticion)
            if faltante > 0:
                time.sleep(faltante)
        self._ultima_peticion = time.monotonic()

    def _pedir(self, url: str, permitir_404: bool = False, **kwargs: Any) -> Any:
        fallos = 0
        limites = 0
        ultimo_error = ""

        while fallos < INTENTOS_MAXIMOS and limites < INTENTOS_MAXIMOS_LIMITE:
            self._respetar_limite()
            try:
                respuesta = self._sesion.get(
                    url, timeout=TIEMPO_LIMITE_SEGUNDOS, **kwargs
                )
            except requests.RequestException as error:
                ultimo_error = str(error)
                time.sleep(ESPERA_BASE_SEGUNDOS * (2**fallos))
                fallos += 1
                continue

            if respuesta.status_code in (401, 403):
                raise CloudTalkAuthError(
                    "CloudTalk rechazó la petición. Revise las variables "
                    "CLOUDTALK_API_KEY_ID y CLOUDTALK_API_KEY_SECRET, y que la "
                    "cuenta tenga Conversation Intelligence para las "
                    "transcripciones."
                )
            if respuesta.status_code == 404 and permitir_404:
                return None
            if respuesta.status_code < 400:
                return respuesta.json()
            if respuesta.status_code == 429:
                ultimo_error = "HTTP 429"
                self._frenar()
                self._esperar_limite(respuesta)
                limites += 1
                continue
            if respuesta.status_code < 500:
                raise CloudTalkError(
                    f"CloudTalk respondió {respuesta.status_code} en {url}: "
                    f"{respuesta.text[:200]}"
                )
            ultimo_error = f"HTTP {respuesta.status_code}"
            time.sleep(ESPERA_BASE_SEGUNDOS * (2**fallos))
            fallos += 1

        raise CloudTalkError(
            f"CloudTalk no respondió tras {fallos + limites} intentos en {url} "
            f"(último error: {ultimo_error})."
        )

    def _frenar(self) -> None:
        self._intervalo = min(
            INTERVALO_MAXIMO_SEGUNDOS, self._intervalo * FACTOR_FRENADO
        )

    def _esperar_limite(self, respuesta: requests.Response) -> None:
        espera = ESPERA_LIMITE_SEGUNDOS
        cabecera = respuesta.headers.get("Retry-After")
        if cabecera:
            try:
                espera = float(cabecera)
            except ValueError:
                pass
        espera = max(0.0, min(espera, ESPERA_LIMITE_MAXIMA_SEGUNDOS))
        if self._al_esperar:
            self._al_esperar(espera)
        time.sleep(espera)

    def listar_llamadas(self, desde: datetime, hasta: datetime) -> list[dict]:
        """Devuelve las llamadas contestadas que empezaron dentro del rango.

        Las perdidas no tienen conversación que transcribir, así que se
        excluyen desde el filtro.
        """
        llamadas: list[dict] = []

        for pagina in range(1, PAGINAS_MAXIMAS + 1):
            datos = self._pedir(
                f"{self._base}/calls/index.json",
                params={
                    "date_from": _a_texto_utc(desde - MARGEN_FILTRO),
                    "date_to": _a_texto_utc(hasta + MARGEN_FILTRO),
                    "status": "answered",
                    "limit": TAMANO_PAGINA_LLAMADAS,
                    "page": pagina,
                },
            )
            respuesta = (datos or {}).get("responseData") or {}
            lote = respuesta.get("data") or []
            llamadas.extend(lote)

            try:
                total_paginas = int(respuesta.get("pageCount") or 0)
            except (TypeError, ValueError):
                total_paginas = 0
            if not lote or pagina >= total_paginas:
                break

        return [ll for ll in llamadas if _dentro_del_rango(ll, desde, hasta)]

    def obtener_transcripcion(self, call_id: str) -> dict | None:
        """Devuelve la transcripción de una llamada, o None si no tiene.

        Junta todas las páginas de segmentos en un solo objeto con la forma de
        `data` en la respuesta de la API.
        """
        url = f"{self._base_ai}/ai/calls/{call_id}/transcription"
        segmentos: list[dict] = []
        transcripcion: dict | None = None

        for _ in range(PAGINAS_MAXIMAS):
            datos = self._pedir(
                url,
                permitir_404=True,
                params={"limit": TAMANO_PAGINA_SEGMENTOS, "offset": len(segmentos)},
            )
            if datos is None:
                return None

            contenido = datos.get("data") or {}
            if transcripcion is None:
                transcripcion = dict(contenido)
            lote = contenido.get("segments") or []
            segmentos.extend(lote)

            try:
                total = int((datos.get("pagination") or {}).get("total") or 0)
            except (TypeError, ValueError):
                total = 0
            if not lote or len(segmentos) >= total:
                break

        if transcripcion is None:
            return None
        transcripcion["segments"] = segmentos
        return transcripcion
