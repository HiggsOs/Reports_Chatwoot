"""Cliente HTTP de la API de Chatwoot."""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

INTENTOS_MAXIMOS = 5
ESPERA_BASE_SEGUNDOS = 1.0
TIEMPO_LIMITE_SEGUNDOS = 30


FORMATO_FECHA_FILTRO = "%Y-%m-%d %H:%M:%S"


# Chatwoot compara created_at por día, no por hora. Se pide un día de más por
# cada lado para no perder los bordes, y el recorte fino se hace en el cliente.
MARGEN_FILTRO = timedelta(days=1)


def _a_texto_utc(momento: datetime) -> str:
    """Convierte a UTC y formatea como texto, que es lo que acepta el filtro."""
    return momento.astimezone(timezone.utc).strftime(FORMATO_FECHA_FILTRO)


def _dentro_del_rango(conversacion: dict, desde: datetime, hasta: datetime) -> bool:
    """Recorta con la hora exacta lo que la API solo supo acotar por día."""
    creada = conversacion.get("created_at")
    if not creada:
        return False
    momento = datetime.fromtimestamp(float(creada), timezone.utc)
    return desde <= momento <= hasta


class ChatwootError(Exception):
    """Falló la comunicación con Chatwoot."""


class ChatwootAuthError(ChatwootError):
    """El token de acceso fue rechazado."""


class ClienteChatwoot:
    def __init__(
        self,
        base_url: str,
        account_id: int,
        api_token: str,
        sesion: requests.Session | None = None,
    ) -> None:
        self._base = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}"
        self._sesion = sesion or requests.Session()
        self._sesion.headers.update(
            {"api_access_token": api_token, "Content-Type": "application/json"}
        )

    def _pedir(self, metodo: str, ruta: str, **kwargs: Any) -> dict:
        url = f"{self._base}{ruta}"
        ultimo_error = ""

        for intento in range(INTENTOS_MAXIMOS):
            try:
                respuesta = self._sesion.request(
                    metodo, url, timeout=TIEMPO_LIMITE_SEGUNDOS, **kwargs
                )
            except requests.RequestException as error:
                ultimo_error = str(error)
            else:
                if respuesta.status_code in (401, 403):
                    raise ChatwootAuthError(
                        "Chatwoot rechazó el token de acceso. "
                        "Revise la variable CHATWOOT_API_TOKEN."
                    )
                if respuesta.status_code < 400:
                    return respuesta.json()
                if respuesta.status_code != 429 and respuesta.status_code < 500:
                    raise ChatwootError(
                        f"Chatwoot respondió {respuesta.status_code} en {ruta}: "
                        f"{respuesta.text[:200]}"
                    )
                ultimo_error = f"HTTP {respuesta.status_code}"
                self._esperar(respuesta, intento)
                continue

            time.sleep(ESPERA_BASE_SEGUNDOS * (2**intento))

        raise ChatwootError(
            f"Chatwoot no respondió tras {INTENTOS_MAXIMOS} intentos en {ruta} "
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

    def listar_conversaciones(self, desde: datetime, hasta: datetime) -> list[dict]:
        """Devuelve las conversaciones creadas dentro del rango, en cualquier estado.

        Chatwoot rechaza un epoch numérico con error 500, y compara `created_at`
        a granularidad de día ignorando la hora, con operadores estrictos: pedir
        un solo día devuelve cero, porque ningún día está estrictamente entre el
        día pedido y el siguiente. Por eso se consulta un rango ampliado en un
        día por lado y se recorta aquí con la hora exacta. De paso, el recorte
        local vuelve irrelevante en qué zona horaria interprete Chatwoot el texto.
        """
        filtro = {
            "payload": [
                {
                    "attribute_key": "created_at",
                    "filter_operator": "is_greater_than",
                    "values": [_a_texto_utc(desde - MARGEN_FILTRO)],
                    "query_operator": "AND",
                    "attribute_model": "standard",
                },
                {
                    "attribute_key": "created_at",
                    "filter_operator": "is_less_than",
                    "values": [_a_texto_utc(hasta + MARGEN_FILTRO)],
                    "attribute_model": "standard",
                },
            ]
        }

        conversaciones: list[dict] = []
        pagina = 1
        while True:
            datos = self._pedir(
                "POST", f"/conversations/filter?page={pagina}", json=filtro
            )
            lote = datos.get("payload") or []
            if not lote:
                break
            conversaciones.extend(lote)
            pagina += 1

        return [c for c in conversaciones if _dentro_del_rango(c, desde, hasta)]

    def listar_inboxes(self) -> dict[int, str]:
        """Devuelve id de inbox → nombre, para saber por qué canal entró cada
        conversación. Se consulta una sola vez por reporte."""
        datos = self._pedir("GET", "/inboxes")
        return {
            inbox["id"]: inbox.get("name") or ""
            for inbox in (datos.get("payload") or [])
            if inbox.get("id") is not None
        }

    def listar_mensajes(self, conversacion_id: int) -> list[dict]:
        """Devuelve todos los mensajes, del más antiguo al más reciente."""
        ruta = f"/conversations/{conversacion_id}/messages"
        recolectados: list[dict] = []
        antes: int | None = None

        while True:
            sufijo = f"?before={antes}" if antes is not None else ""
            datos = self._pedir("GET", f"{ruta}{sufijo}")
            lote = datos.get("payload") or []
            if not lote:
                break
            siguiente = min(m["id"] for m in lote)
            if antes is not None and siguiente >= antes:
                break
            recolectados.extend(lote)
            antes = siguiente

        return sorted(recolectados, key=lambda m: m["id"])


class CacheMensajes:
    """Guarda en disco los mensajes de conversaciones ya resueltas."""

    def __init__(self, directorio: Path) -> None:
        self._directorio = directorio

    def _archivo(self, conversacion_id: int) -> Path:
        return self._directorio / f"{conversacion_id}.json"

    def leer(self, conversacion_id: int) -> list[dict] | None:
        archivo = self._archivo(conversacion_id)
        if not archivo.exists():
            return None
        try:
            return json.loads(archivo.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def guardar(self, conversacion_id: int, mensajes: list[dict]) -> None:
        self._directorio.mkdir(parents=True, exist_ok=True)
        self._archivo(conversacion_id).write_text(
            json.dumps(mensajes, ensure_ascii=False), encoding="utf-8"
        )
