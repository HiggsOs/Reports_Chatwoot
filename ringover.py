"""Cliente HTTP de la API pública de Ringover."""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

BASE_URL_POR_DEFECTO = "https://public-api.ringover.com/v2"

INTENTOS_MAXIMOS = 5
ESPERA_BASE_SEGUNDOS = 1.0
TIEMPO_LIMITE_SEGUNDOS = 60

# La API rechaza con 422 cualquier página mayor a 100.
TAMANO_PAGINA = 100

# /calls admite páginas mucho más grandes, pero no rangos de más de 15 días.
TAMANO_PAGINA_LLAMADAS = 1000
RANGO_MAXIMO_LLAMADAS = timedelta(days=15)

# Tope de seguridad: sin él, una API que ignorara el offset dejaría el reporte
# pidiendo páginas para siempre.
PAGINAS_MAXIMAS = 200

FORMATO_FECHA_API = "%Y-%m-%dT%H:%M:%SZ"


def _a_texto_utc(momento: datetime) -> str:
    """Formatea en UTC con ISO 8601, que es lo único que acepta el filtro."""
    return momento.astimezone(timezone.utc).strftime(FORMATO_FECHA_API)


class RingoverError(Exception):
    """Falló la comunicación con Ringover."""


class RingoverAuthError(RingoverError):
    """El token fue rechazado, o el equipo no tiene transcripciones habilitadas."""


class ClienteRingover:
    def __init__(
        self,
        api_token: str,
        base_url: str = BASE_URL_POR_DEFECTO,
        sesion: requests.Session | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._sesion = sesion or requests.Session()
        self._sesion.headers.update({"Authorization": api_token})

    def _pedir(self, ruta: str, **kwargs: Any) -> Any:
        url = f"{self._base}{ruta}"
        ultimo_error = ""

        for intento in range(INTENTOS_MAXIMOS):
            try:
                respuesta = self._sesion.get(
                    url, timeout=TIEMPO_LIMITE_SEGUNDOS, **kwargs
                )
            except requests.RequestException as error:
                ultimo_error = str(error)
            else:
                if respuesta.status_code in (401, 403):
                    raise RingoverAuthError(
                        "Ringover rechazó la petición. Revise la variable "
                        "RINGOVER_API_TOKEN y que su equipo tenga habilitada la "
                        "función de transcripciones."
                    )
                # 204: no hay transcripciones en el rango, y el cuerpo va vacío.
                if respuesta.status_code == 204:
                    return []
                if respuesta.status_code < 400:
                    return respuesta.json()
                if respuesta.status_code != 429 and respuesta.status_code < 500:
                    raise RingoverError(
                        f"Ringover respondió {respuesta.status_code} en {ruta}: "
                        f"{respuesta.text[:200]}"
                    )
                ultimo_error = f"HTTP {respuesta.status_code}"
                self._esperar(respuesta, intento)
                continue

            time.sleep(ESPERA_BASE_SEGUNDOS * (2**intento))

        raise RingoverError(
            f"Ringover no respondió tras {INTENTOS_MAXIMOS} intentos en {ruta} "
            f"(último error: {ultimo_error})."
        )

    def _esperar(self, respuesta: requests.Response, intento: int) -> None:
        cabecera = respuesta.headers.get("Retry-After")
        if cabecera:
            try:
                time.sleep(float(cabecera))
                return
            except ValueError:
                pass
        time.sleep(ESPERA_BASE_SEGUNDOS * (2**intento))

    def listar_transcripciones(
        self, desde: datetime, hasta: datetime, al_avanzar=None
    ) -> list[dict]:
        """Devuelve las transcripciones creadas dentro del rango.

        El filtro de Ringover es inclusivo en ambos extremos y se expresa en UTC,
        así que basta con convertir el rango local. El texto completo se trae por
        fila, por lo que la API limita cada página a 100 y hay que paginar con
        `limit_offset`.
        """
        transcripciones: list[dict] = []

        for pagina in range(PAGINAS_MAXIMAS):
            datos = self._pedir(
                "/transcriptions",
                params={
                    "created_from": _a_texto_utc(desde),
                    "created_to": _a_texto_utc(hasta),
                    "limit_count": TAMANO_PAGINA,
                    "limit_offset": pagina * TAMANO_PAGINA,
                },
            )
            lote = _extraer_lista(datos)
            if not lote:
                break
            transcripciones.extend(lote)
            if al_avanzar:
                al_avanzar(len(transcripciones))
            if len(lote) < TAMANO_PAGINA:
                break

        return transcripciones


    def listar_direcciones(self, desde: datetime, hasta: datetime) -> dict[str, str]:
        """Devuelve `call_id` → dirección (`in` o `out`) de las llamadas del rango.

        Las transcripciones no dicen quién emitió la llamada, y sin eso no se
        puede saber si el canal 0 es el agente o el cliente. El registro de
        llamadas sí lo expone, así que se consulta una vez por reporte.

        `/calls` no acepta rangos de más de 15 días, de modo que el rango se
        parte en ventanas, y se pagina con el cursor `last_id_returned` en vez
        del desplazamiento, que la API corta a las 9000 filas.
        """
        direcciones: dict[str, str] = {}

        for inicio, fin in _ventanas(desde, hasta, RANGO_MAXIMO_LLAMADAS):
            cursor: int | None = None

            for _ in range(PAGINAS_MAXIMAS):
                parametros = {
                    "start_date": _a_texto_utc(inicio),
                    "end_date": _a_texto_utc(fin),
                    "limit_count": TAMANO_PAGINA_LLAMADAS,
                }
                if cursor is not None:
                    parametros["last_id_returned"] = cursor

                datos = self._pedir("/calls", params=parametros)
                lote = _extraer_lista(datos)
                if not lote:
                    break

                for llamada in lote:
                    call_id = llamada.get("call_id")
                    direccion = (llamada.get("direction") or "").strip().lower()
                    # Una llamada transferida deja varios registros con el mismo
                    # call_id; el primero es el que le dio origen.
                    if call_id and direccion:
                        direcciones.setdefault(str(call_id), direccion)

                if len(lote) < TAMANO_PAGINA_LLAMADAS:
                    break

                siguiente = _menor_cdr(lote)
                if siguiente is None or (cursor is not None and siguiente >= cursor):
                    break
                cursor = siguiente

        return direcciones


def _ventanas(desde: datetime, hasta: datetime, ancho: timedelta):
    """Parte el rango en tramos que no superen el ancho permitido."""
    inicio = desde
    while inicio <= hasta:
        fin = min(hasta, inicio + ancho - timedelta(seconds=1))
        yield inicio, fin
        inicio = fin + timedelta(seconds=1)


def _menor_cdr(lote: list[dict]) -> int | None:
    """El cursor pide los registros anteriores al `cdr_id` que se le pase."""
    identificadores = []
    for llamada in lote:
        try:
            identificadores.append(int(llamada["cdr_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return min(identificadores) if identificadores else None


def _extraer_lista(datos: Any) -> list[dict]:
    """La API documenta un arreglo, pero otros endpoints envuelven en `list`."""
    if isinstance(datos, list):
        return datos
    if isinstance(datos, dict):
        for clave in ("list", "transcriptions", "call_list"):
            valor = datos.get(clave)
            if isinstance(valor, list):
                return valor
    return []
