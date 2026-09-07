# Reporte de Chatwoot — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir una app web con login que genere, para un rango de fechas
elegido, un CSV de conversaciones de Chatwoot con asesor, fecha, etiquetas,
tiempo de resolución, dirección, fecha de cierre y área (Comercial/RDC).

**Architecture:** Dos capas estrictamente separadas. El núcleo (`config.py`,
`chatwoot.py`, `reporte.py`) son funciones puras y un cliente HTTP que no
importan Streamlit. La interfaz (`app.py`) solo llama al núcleo. El contenedor
se despliega en EasyPanel con un volumen persistente en `/data`.

**Tech Stack:** Python 3.12, `requests`, `streamlit`, `streamlit-authenticator`,
`bcrypt`, `pytest`, `responses`, Docker.

**Spec:** `docs/superpowers/specs/2026-09-07-reporte-chatwoot-design.md`

## Global Constraints

- Python 3.12. Imagen base `python:3.12-slim`.
- Zona horaria de todas las fechas mostradas y escritas: `America/Bogota`.
- Todo el texto visible al usuario y todos los nombres de columnas del CSV van
  en español. Los nombres de funciones y variables también van en español, para
  ser consistentes con el dominio.
- El núcleo (`config.py`, `chatwoot.py`, `reporte.py`) NUNCA importa
  `streamlit`. Un `import streamlit` en esos archivos es un error de diseño.
- Ningún secreto en el repositorio. Credenciales solo por variables de entorno.
- Los datos persistentes viven en el directorio indicado por `Config.data_dir`
  (`/data` en producción). Ninguna ruta a `/data` puede estar escrita a mano
  fuera de `config.py`.
- Los tests nunca hacen llamadas de red reales. Se usa `responses` para simular
  HTTP.
- Estados de Chatwoot traducidos así: `open`→`abierta`, `pending`→`pendiente`,
  `resolved`→`resuelta`, `snoozed`→`pospuesta`.

---

### Task 1: Andamiaje del proyecto y configuración

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `.env.example`
- Create: `tests/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nada.
- Produces: `ConfigError(Exception)`; `Config` (dataclass congelado con campos
  `base_url: str`, `account_id: int`, `api_token: str`, `usuario: str`,
  `password_hash: str`, `cookie_key: str`, `data_dir: Path`);
  `cargar_config(entorno: Mapping[str, str]) -> Config`;
  `ruta_asesores(cfg: Config) -> Path`; `ruta_cache(cfg: Config) -> Path`.

- [ ] **Step 1: Crear `requirements.txt`**

```
streamlit==1.39.0
streamlit-authenticator==0.3.3
requests==2.32.3
bcrypt==4.2.0
pytest==8.3.3
responses==0.25.3
```

- [ ] **Step 2: Escribir el test que falla**

Crear `tests/__init__.py` vacío y `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from config import Config, ConfigError, cargar_config, ruta_asesores, ruta_cache

ENTORNO_VALIDO = {
    "CHATWOOT_BASE_URL": "https://chat.ejemplo.com/",
    "CHATWOOT_ACCOUNT_ID": "3",
    "CHATWOOT_API_TOKEN": "token-secreto",
    "APP_USERNAME": "reportes",
    "APP_PASSWORD_HASH": "$2b$12$abcdefghijklmnopqrstuv",
    "APP_COOKIE_KEY": "clave-de-cookie",
    "DATA_DIR": "/data",
}


def test_carga_configuracion_completa():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert isinstance(cfg, Config)
    assert cfg.account_id == 3
    assert cfg.api_token == "token-secreto"
    assert cfg.data_dir == Path("/data")


def test_quita_la_barra_final_de_la_url():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert cfg.base_url == "https://chat.ejemplo.com"


def test_data_dir_tiene_valor_por_defecto():
    entorno = {k: v for k, v in ENTORNO_VALIDO.items() if k != "DATA_DIR"}
    assert cargar_config(entorno).data_dir == Path("/data")


def test_falta_una_variable():
    entorno = {k: v for k, v in ENTORNO_VALIDO.items() if k != "CHATWOOT_API_TOKEN"}
    with pytest.raises(ConfigError) as error:
        cargar_config(entorno)
    assert "CHATWOOT_API_TOKEN" in str(error.value)


def test_variable_vacia_cuenta_como_faltante():
    with pytest.raises(ConfigError) as error:
        cargar_config({**ENTORNO_VALIDO, "APP_COOKIE_KEY": "   "})
    assert "APP_COOKIE_KEY" in str(error.value)


def test_reporta_todas_las_variables_faltantes_juntas():
    with pytest.raises(ConfigError) as error:
        cargar_config({"CHATWOOT_BASE_URL": "https://x.com"})
    mensaje = str(error.value)
    assert "CHATWOOT_ACCOUNT_ID" in mensaje
    assert "APP_USERNAME" in mensaje


def test_account_id_no_numerico():
    with pytest.raises(ConfigError) as error:
        cargar_config({**ENTORNO_VALIDO, "CHATWOOT_ACCOUNT_ID": "abc"})
    assert "CHATWOOT_ACCOUNT_ID" in str(error.value)


def test_rutas_derivadas_del_data_dir():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert ruta_asesores(cfg) == Path("/data/asesores.csv")
    assert ruta_cache(cfg) == Path("/data/cache")
```

- [ ] **Step 3: Ejecutar los tests y verificar que fallan**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 4: Escribir la implementación mínima**

Crear `config.py`:

```python
"""Lectura y validación de la configuración por variables de entorno."""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DATA_DIR_POR_DEFECTO = "/data"

_REQUERIDAS = (
    "CHATWOOT_BASE_URL",
    "CHATWOOT_ACCOUNT_ID",
    "CHATWOOT_API_TOKEN",
    "APP_USERNAME",
    "APP_PASSWORD_HASH",
    "APP_COOKIE_KEY",
)


class ConfigError(Exception):
    """La configuración del entorno es inválida o está incompleta."""


@dataclass(frozen=True)
class Config:
    base_url: str
    account_id: int
    api_token: str
    usuario: str
    password_hash: str
    cookie_key: str
    data_dir: Path


def cargar_config(entorno: Mapping[str, str]) -> Config:
    faltantes = [
        nombre for nombre in _REQUERIDAS if not entorno.get(nombre, "").strip()
    ]
    if faltantes:
        raise ConfigError(
            "Faltan variables de entorno obligatorias: " + ", ".join(faltantes)
        )

    bruto = entorno["CHATWOOT_ACCOUNT_ID"].strip()
    try:
        account_id = int(bruto)
    except ValueError as error:
        raise ConfigError(
            f"CHATWOOT_ACCOUNT_ID debe ser un número entero, se recibió: {bruto!r}"
        ) from error

    data_dir = (entorno.get("DATA_DIR") or DATA_DIR_POR_DEFECTO).strip()

    return Config(
        base_url=entorno["CHATWOOT_BASE_URL"].strip().rstrip("/"),
        account_id=account_id,
        api_token=entorno["CHATWOOT_API_TOKEN"].strip(),
        usuario=entorno["APP_USERNAME"].strip(),
        password_hash=entorno["APP_PASSWORD_HASH"].strip(),
        cookie_key=entorno["APP_COOKIE_KEY"].strip(),
        data_dir=Path(data_dir),
    )


def ruta_asesores(cfg: Config) -> Path:
    return cfg.data_dir / "asesores.csv"


def ruta_cache(cfg: Config) -> Path:
    return cfg.data_dir / "cache"
```

- [ ] **Step 5: Ejecutar los tests y verificar que pasan**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 6: Crear `.env.example`**

```
CHATWOOT_BASE_URL=https://chat.miempresa.com
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_API_TOKEN=
APP_USERNAME=reportes
APP_PASSWORD_HASH=
APP_COOKIE_KEY=
DATA_DIR=/data
TZ=America/Bogota
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt config.py .env.example tests/
git commit -m "Agregar carga y validación de configuración por entorno"
```

---

### Task 2: Cliente de la API — listado de conversaciones

**Files:**
- Create: `chatwoot.py`
- Test: `tests/test_chatwoot.py`

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces: `ChatwootError(Exception)`; `ChatwootAuthError(ChatwootError)`;
  `ClienteChatwoot(base_url: str, account_id: int, api_token: str, sesion:
  requests.Session | None = None)`; método
  `listar_conversaciones(desde: datetime, hasta: datetime) -> list[dict]`.

Las fechas `desde` y `hasta` llegan como `datetime` con zona horaria; el cliente
las convierte a epoch en segundos para el filtro.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_chatwoot.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import responses

from chatwoot import ChatwootAuthError, ChatwootError, ClienteChatwoot

BOGOTA = ZoneInfo("America/Bogota")
DESDE = datetime(2026, 9, 1, 0, 0, tzinfo=BOGOTA)
HASTA = datetime(2026, 9, 30, 23, 59, tzinfo=BOGOTA)

URL_FILTRO = "https://chat.ejemplo.com/api/v1/accounts/7/conversations/filter"


def cliente():
    return ClienteChatwoot("https://chat.ejemplo.com", 7, "token-secreto")


def pagina(ids):
    return {"payload": [{"id": i} for i in ids]}


@responses.activate
def test_recorre_todas_las_paginas():
    responses.post(URL_FILTRO, json=pagina([1, 2]))
    responses.post(URL_FILTRO, json=pagina([3]))
    responses.post(URL_FILTRO, json=pagina([]))

    conversaciones = cliente().listar_conversaciones(DESDE, HASTA)

    assert [c["id"] for c in conversaciones] == [1, 2, 3]
    assert len(responses.calls) == 3


@responses.activate
def test_envia_el_token_y_el_rango_de_fechas():
    responses.post(URL_FILTRO, json=pagina([]))

    cliente().listar_conversaciones(DESDE, HASTA)

    peticion = responses.calls[0].request
    assert peticion.headers["api_access_token"] == "token-secreto"
    cuerpo = peticion.body.decode() if isinstance(peticion.body, bytes) else peticion.body
    assert str(int(DESDE.timestamp())) in cuerpo
    assert str(int(HASTA.timestamp())) in cuerpo


@responses.activate
def test_pide_paginas_consecutivas():
    responses.post(URL_FILTRO, json=pagina([1]))
    responses.post(URL_FILTRO, json=pagina([]))

    cliente().listar_conversaciones(DESDE, HASTA)

    assert "page=1" in responses.calls[0].request.url
    assert "page=2" in responses.calls[1].request.url


@responses.activate
def test_token_invalido_da_error_claro():
    responses.post(URL_FILTRO, status=401, json={"error": "no autorizado"})

    with pytest.raises(ChatwootAuthError) as error:
        cliente().listar_conversaciones(DESDE, HASTA)
    assert "token" in str(error.value).lower()


@responses.activate
def test_error_del_servidor_persistente():
    # Retry-After en 0 para que el test no espere los reintentos reales.
    for _ in range(6):
        responses.post(URL_FILTRO, status=500, headers={"Retry-After": "0"}, json={})

    with pytest.raises(ChatwootError) as error:
        cliente().listar_conversaciones(DESDE, HASTA)
    assert "5 intentos" in str(error.value)
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `python -m pytest tests/test_chatwoot.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'chatwoot'`

- [ ] **Step 3: Escribir la implementación**

Crear `chatwoot.py`. Los reintentos se implementan completos aquí porque
`_pedir` es el único punto por donde pasan todas las peticiones; la Tarea 3 los
prueba a fondo.

```python
"""Cliente HTTP de la API de Chatwoot."""

import time
from datetime import datetime
from typing import Any

import requests

INTENTOS_MAXIMOS = 5
ESPERA_BASE_SEGUNDOS = 1.0
TIEMPO_LIMITE_SEGUNDOS = 30


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
        """Devuelve las conversaciones creadas dentro del rango, en cualquier estado."""
        filtro = {
            "payload": [
                {
                    "attribute_key": "created_at",
                    "filter_operator": "is_greater_than",
                    "values": [int(desde.timestamp())],
                    "query_operator": "AND",
                    "attribute_model": "standard",
                },
                {
                    "attribute_key": "created_at",
                    "filter_operator": "is_less_than",
                    "values": [int(hasta.timestamp())],
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
                return conversaciones
            conversaciones.extend(lote)
            pagina += 1
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `python -m pytest tests/test_chatwoot.py -v`
Expected: PASS, 5 tests. El test de error persistente tarda unos segundos por
las esperas de reintento.

- [ ] **Step 5: Commit**

```bash
git add chatwoot.py tests/test_chatwoot.py
git commit -m "Agregar cliente de Chatwoot con listado paginado de conversaciones"
```

---

### Task 3: Cliente de la API — mensajes, caché y reintentos

**Files:**
- Modify: `chatwoot.py`
- Modify: `tests/test_chatwoot.py`

**Interfaces:**
- Consumes: `ClienteChatwoot`, `ChatwootError` (Tarea 2).
- Produces: método `listar_mensajes(conversacion_id: int) -> list[dict]` que
  devuelve los mensajes del más antiguo al más reciente;
  `CacheMensajes(directorio: Path)` con `leer(conversacion_id: int) ->
  list[dict] | None` y `guardar(conversacion_id: int, mensajes: list[dict]) ->
  None`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_chatwoot.py`:

```python
import json
from pathlib import Path

from chatwoot import CacheMensajes

URL_MENSAJES = "https://chat.ejemplo.com/api/v1/accounts/7/conversations/42/messages"


@responses.activate
def test_mensajes_en_orden_cronologico():
    responses.get(
        URL_MENSAJES,
        json={"payload": [{"id": 10, "content": "b"}, {"id": 5, "content": "a"}]},
    )
    responses.get(URL_MENSAJES, json={"payload": []})

    mensajes = cliente().listar_mensajes(42)

    assert [m["id"] for m in mensajes] == [5, 10]


@responses.activate
def test_mensajes_paginan_hacia_atras_con_before():
    responses.get(URL_MENSAJES, json={"payload": [{"id": 8}, {"id": 9}]})
    responses.get(URL_MENSAJES, json={"payload": [{"id": 3}]})
    responses.get(URL_MENSAJES, json={"payload": []})

    mensajes = cliente().listar_mensajes(42)

    assert [m["id"] for m in mensajes] == [3, 8, 9]
    assert "before=8" in responses.calls[1].request.url
    assert "before=3" in responses.calls[2].request.url


@responses.activate
def test_reintenta_tras_429_y_luego_tiene_exito():
    responses.get(URL_MENSAJES, status=429, headers={"Retry-After": "0"}, json={})
    responses.get(URL_MENSAJES, json={"payload": [{"id": 1}]})
    responses.get(URL_MENSAJES, json={"payload": []})

    mensajes = cliente().listar_mensajes(42)

    assert [m["id"] for m in mensajes] == [1]
    assert len(responses.calls) == 3


def test_cache_devuelve_none_cuando_no_hay_nada(tmp_path: Path):
    assert CacheMensajes(tmp_path).leer(42) is None


def test_cache_guarda_y_recupera(tmp_path: Path):
    cache = CacheMensajes(tmp_path)
    cache.guardar(42, [{"id": 1, "content": "hola"}])
    assert cache.leer(42) == [{"id": 1, "content": "hola"}]


def test_cache_ignora_un_archivo_corrupto(tmp_path: Path):
    cache = CacheMensajes(tmp_path)
    cache.guardar(42, [{"id": 1}])
    (tmp_path / "42.json").write_text("{roto", encoding="utf-8")
    assert cache.leer(42) is None


def test_cache_crea_el_directorio_si_no_existe(tmp_path: Path):
    destino = tmp_path / "sub" / "cache"
    CacheMensajes(destino).guardar(1, [])
    assert (destino / "1.json").exists()
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `python -m pytest tests/test_chatwoot.py -v`
Expected: FAIL con `ImportError: cannot import name 'CacheMensajes'`

- [ ] **Step 3: Escribir la implementación**

Agregar al principio de `chatwoot.py` los imports `json` y
`from pathlib import Path`, y luego este método a `ClienteChatwoot`:

```python
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
            recolectados.extend(lote)
            siguiente = min(m["id"] for m in lote)
            if antes is not None and siguiente >= antes:
                break
            antes = siguiente

        return sorted(recolectados, key=lambda m: m["id"])
```

Y esta clase al final del archivo:

```python
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
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `python -m pytest tests/test_chatwoot.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Commit**

```bash
git add chatwoot.py tests/test_chatwoot.py
git commit -m "Agregar lectura paginada de mensajes y caché en disco"
```

---

### Task 4: Mapeo de asesores a áreas

**Files:**
- Create: `reporte.py`
- Test: `tests/test_reporte.py`

**Interfaces:**
- Consumes: nada.
- Produces: `AREAS_VALIDAS = ("Comercial", "RDC")`;
  `cargar_asesores(ruta: Path) -> dict[str, str]` (correo en minúsculas → área);
  `guardar_asesores(ruta: Path, mapeo: dict[str, str]) -> None`;
  `resolver_area(email: str | None, mapeo: dict[str, str]) -> str`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_reporte.py`:

```python
from pathlib import Path

from reporte import cargar_asesores, guardar_asesores, resolver_area


def test_archivo_inexistente_da_mapeo_vacio(tmp_path: Path):
    assert cargar_asesores(tmp_path / "no-existe.csv") == {}


def test_carga_normaliza_correos_y_espacios(tmp_path: Path):
    archivo = tmp_path / "asesores.csv"
    archivo.write_text(
        "email_asesor,area\n  Ana@Empresa.com , Comercial \nluis@empresa.com,RDC\n",
        encoding="utf-8",
    )
    assert cargar_asesores(archivo) == {
        "ana@empresa.com": "Comercial",
        "luis@empresa.com": "RDC",
    }


def test_ida_y_vuelta_de_guardado(tmp_path: Path):
    archivo = tmp_path / "sub" / "asesores.csv"
    mapeo = {"ana@empresa.com": "Comercial", "luis@empresa.com": "RDC"}
    guardar_asesores(archivo, mapeo)
    assert cargar_asesores(archivo) == mapeo


def test_guardar_ordena_por_correo(tmp_path: Path):
    archivo = tmp_path / "asesores.csv"
    guardar_asesores(archivo, {"zoe@e.com": "RDC", "ana@e.com": "Comercial"})
    lineas = archivo.read_text(encoding="utf-8").splitlines()
    assert lineas[1].startswith("ana@e.com")


def test_resolver_area_encuentra_al_asesor():
    assert resolver_area("Ana@Empresa.com", {"ana@empresa.com": "RDC"}) == "RDC"


def test_asesor_sin_mapear():
    assert resolver_area("nuevo@empresa.com", {}) == "SIN_MAPEAR"


def test_conversacion_sin_asesor_asignado():
    assert resolver_area(None, {"ana@empresa.com": "RDC"}) == "SIN_ASIGNAR"
    assert resolver_area("", {}) == "SIN_ASIGNAR"
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `python -m pytest tests/test_reporte.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'reporte'`

- [ ] **Step 3: Escribir la implementación**

Crear `reporte.py`:

```python
"""Armado del reporte de conversaciones a partir de los datos de Chatwoot."""

import csv
from pathlib import Path

AREAS_VALIDAS = ("Comercial", "RDC")
SIN_MAPEAR = "SIN_MAPEAR"
SIN_ASIGNAR = "SIN_ASIGNAR"

_ENCABEZADOS_ASESORES = ("email_asesor", "area")


def cargar_asesores(ruta: Path) -> dict[str, str]:
    """Lee el mapeo correo → área. Devuelve vacío si el archivo no existe."""
    if not ruta.exists():
        return {}

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        filas = csv.DictReader(archivo)
        return {
            (fila.get("email_asesor") or "").strip().lower(): (
                fila.get("area") or ""
            ).strip()
            for fila in filas
            if (fila.get("email_asesor") or "").strip()
        }


def guardar_asesores(ruta: Path, mapeo: dict[str, str]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(_ENCABEZADOS_ASESORES)
        for correo in sorted(mapeo):
            escritor.writerow([correo, mapeo[correo]])


def resolver_area(email: str | None, mapeo: dict[str, str]) -> str:
    if not email or not email.strip():
        return SIN_ASIGNAR
    return mapeo.get(email.strip().lower(), SIN_MAPEAR)
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `python -m pytest tests/test_reporte.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add reporte.py tests/test_reporte.py
git commit -m "Agregar mapeo de asesores a áreas Comercial y RDC"
```

---

### Task 5: Dirección de la conversación y fecha de cierre

**Files:**
- Modify: `reporte.py`
- Modify: `tests/test_reporte.py`

**Interfaces:**
- Consumes: `reporte.py` (Tarea 4).
- Produces: `TZ` (`ZoneInfo("America/Bogota")`);
  `detectar_direccion(mensajes: list[dict]) -> str` que devuelve `"Entrante"`,
  `"Saliente"` o `"Indeterminado"`;
  `detectar_cierre(conversacion: dict, mensajes: list[dict]) ->
  tuple[datetime | None, bool]` que devuelve la fecha de cierre con zona horaria
  y si fue aproximada; `traducir_estado(estado: str) -> str`;
  `a_fecha_local(epoch: int | float | None) -> datetime | None`.

Implementa la sección 5.3 de la especificación: cascada de tres pasos para la
fecha de cierre.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_reporte.py`:

```python
from datetime import datetime

from reporte import (
    TZ,
    a_fecha_local,
    detectar_cierre,
    detectar_direccion,
    traducir_estado,
)

# 2026-09-05 10:00 en Bogotá
EPOCH_CREACION = int(datetime(2026, 9, 5, 10, 0, tzinfo=TZ).timestamp())
EPOCH_CIERRE = int(datetime(2026, 9, 5, 14, 30, tzinfo=TZ).timestamp())


def mensaje(id_, tipo, contenido="", creado=EPOCH_CREACION):
    return {"id": id_, "message_type": tipo, "content": contenido, "created_at": creado}


def test_direccion_entrante():
    mensajes = [mensaje(1, 0, "hola"), mensaje(2, 1, "buenas")]
    assert detectar_direccion(mensajes) == "Entrante"


def test_direccion_saliente():
    mensajes = [mensaje(1, 1, "le escribimos"), mensaje(2, 0, "gracias")]
    assert detectar_direccion(mensajes) == "Saliente"


def test_direccion_ignora_actividades_previas():
    mensajes = [mensaje(1, 2, "Conversación asignada"), mensaje(2, 0, "hola")]
    assert detectar_direccion(mensajes) == "Entrante"


def test_direccion_indeterminada_sin_mensajes():
    assert detectar_direccion([]) == "Indeterminado"
    assert detectar_direccion([mensaje(1, 2, "actividad")]) == "Indeterminado"


def test_cierre_desde_actividad_en_espanol():
    conversacion = {"status": "resolved", "last_activity_at": EPOCH_CIERRE + 9999}
    mensajes = [
        mensaje(1, 0, "hola"),
        mensaje(2, 2, "Ana marcó la conversación como resuelta", EPOCH_CIERRE),
    ]
    fecha, aproximado = detectar_cierre(conversacion, mensajes)
    assert fecha == datetime.fromtimestamp(EPOCH_CIERRE, TZ)
    assert aproximado is False


def test_cierre_desde_actividad_en_ingles():
    conversacion = {"status": "resolved", "last_activity_at": EPOCH_CIERRE + 9999}
    mensajes = [mensaje(2, 2, "Conversation was marked resolved by Ana", EPOCH_CIERRE)]
    fecha, aproximado = detectar_cierre(conversacion, mensajes)
    assert fecha == datetime.fromtimestamp(EPOCH_CIERRE, TZ)
    assert aproximado is False


def test_cierre_toma_la_resolucion_mas_reciente_si_se_reabrio():
    posterior = EPOCH_CIERRE + 86400
    conversacion = {"status": "resolved", "last_activity_at": posterior}
    mensajes = [
        mensaje(2, 2, "marcó la conversación como resuelta", EPOCH_CIERRE),
        mensaje(3, 2, "reabrió la conversación", EPOCH_CIERRE + 100),
        mensaje(4, 2, "marcó la conversación como resuelta", posterior),
    ]
    fecha, aproximado = detectar_cierre(conversacion, mensajes)
    assert fecha == datetime.fromtimestamp(posterior, TZ)
    assert aproximado is False


def test_cierre_aproximado_cuando_no_hay_actividad_reconocible():
    conversacion = {"status": "resolved", "last_activity_at": EPOCH_CIERRE}
    mensajes = [mensaje(1, 0, "hola")]
    fecha, aproximado = detectar_cierre(conversacion, mensajes)
    assert fecha == datetime.fromtimestamp(EPOCH_CIERRE, TZ)
    assert aproximado is True


def test_sin_cierre_si_la_conversacion_sigue_abierta():
    conversacion = {"status": "open", "last_activity_at": EPOCH_CIERRE}
    assert detectar_cierre(conversacion, []) == (None, False)


def test_traduccion_de_estados():
    assert traducir_estado("open") == "abierta"
    assert traducir_estado("pending") == "pendiente"
    assert traducir_estado("resolved") == "resuelta"
    assert traducir_estado("snoozed") == "pospuesta"
    assert traducir_estado("otro") == "otro"


def test_conversion_de_epoch_a_hora_local():
    assert a_fecha_local(None) is None
    assert a_fecha_local(EPOCH_CREACION).hour == 10
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `python -m pytest tests/test_reporte.py -v`
Expected: FAIL con `ImportError: cannot import name 'TZ'`

- [ ] **Step 3: Escribir la implementación**

Agregar a `reporte.py` los imports `re` y
`from datetime import datetime`, `from zoneinfo import ZoneInfo`, y luego:

```python
TZ = ZoneInfo("America/Bogota")

ENTRANTE = "Entrante"
SALIENTE = "Saliente"
INDETERMINADO = "Indeterminado"

TIPO_ENTRANTE = 0
TIPO_SALIENTE = 1
TIPO_ACTIVIDAD = 2

# El texto de la actividad depende del idioma configurado en Chatwoot.
_PATRON_RESOLUCION = re.compile(r"resolv(ed|ió)|resuelt[ao]", re.IGNORECASE)
_PATRON_REAPERTURA = re.compile(r"reopen|reabr", re.IGNORECASE)

_ESTADOS = {
    "open": "abierta",
    "pending": "pendiente",
    "resolved": "resuelta",
    "snoozed": "pospuesta",
}


def traducir_estado(estado: str) -> str:
    return _ESTADOS.get(estado, estado)


def a_fecha_local(epoch: int | float | None) -> datetime | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), TZ)


def detectar_direccion(mensajes: list[dict]) -> str:
    """Mira el primer mensaje real: define si el contacto o el asesor inició."""
    for msg in mensajes:
        tipo = msg.get("message_type")
        if tipo == TIPO_ENTRANTE:
            return ENTRANTE
        if tipo == TIPO_SALIENTE:
            return SALIENTE
    return INDETERMINADO


def detectar_cierre(
    conversacion: dict, mensajes: list[dict]
) -> tuple[datetime | None, bool]:
    """Devuelve (fecha de cierre, si es aproximada). Ver sección 5.3 del diseño."""
    if conversacion.get("status") != "resolved":
        return None, False

    resoluciones = [
        msg.get("created_at")
        for msg in mensajes
        if msg.get("message_type") == TIPO_ACTIVIDAD
        and _PATRON_RESOLUCION.search(msg.get("content") or "")
        and not _PATRON_REAPERTURA.search(msg.get("content") or "")
    ]
    if resoluciones:
        return a_fecha_local(max(resoluciones)), False

    return a_fecha_local(conversacion.get("last_activity_at")), True
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `python -m pytest tests/test_reporte.py -v`
Expected: PASS, 18 tests.

- [ ] **Step 5: Commit**

```bash
git add reporte.py tests/test_reporte.py
git commit -m "Detectar dirección de la conversación y fecha de cierre"
```

---

### Task 6: Armado de filas y escritura del CSV

**Files:**
- Modify: `reporte.py`
- Modify: `tests/test_reporte.py`

**Interfaces:**
- Consumes: todo lo de las Tareas 4 y 5; `ClienteChatwoot` y `CacheMensajes`
  (Tareas 2 y 3).
- Produces: `COLUMNAS: tuple[str, ...]`;
  `construir_fila(conversacion: dict, mensajes: list[dict], mapeo: dict[str, str])
  -> dict[str, str]`;
  `generar_filas(cliente, desde, hasta, mapeo, cache=None, al_avanzar=None)
  -> list[dict[str, str]]`;
  `escribir_csv(filas: list[dict[str, str]]) -> bytes`;
  `nombre_archivo(desde: date, hasta: date) -> str`.

`al_avanzar` es una función opcional `(hechas: int, total: int) -> None` que la
interfaz usa para la barra de progreso. El núcleo no sabe qué hace con eso.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_reporte.py`:

```python
from datetime import date

from reporte import (
    COLUMNAS,
    construir_fila,
    escribir_csv,
    generar_filas,
    nombre_archivo,
)

MAPEO = {"ana@empresa.com": "Comercial", "luis@empresa.com": "RDC"}


def conversacion(**cambios):
    base = {
        "id": 101,
        "status": "resolved",
        "created_at": EPOCH_CREACION,
        "last_activity_at": EPOCH_CIERRE,
        "labels": ["cotizacion", "whatsapp"],
        "meta": {"assignee": {"name": "Ana Pérez", "email": "Ana@Empresa.com"}},
    }
    base.update(cambios)
    return base


MENSAJES = [
    mensaje(1, 0, "hola"),
    mensaje(2, 2, "Ana marcó la conversación como resuelta", EPOCH_CIERRE),
]


def test_fila_completa():
    fila = construir_fila(conversacion(), MENSAJES, MAPEO)
    assert fila["conversacion_id"] == "101"
    assert fila["asesor"] == "Ana Pérez"
    assert fila["email_asesor"] == "Ana@Empresa.com"
    assert fila["area"] == "Comercial"
    assert fila["fecha_creacion"] == "2026-09-05 10:00"
    assert fila["etiquetas"] == "cotizacion;whatsapp"
    assert fila["direccion"] == "Entrante"
    assert fila["estado"] == "resuelta"
    assert fila["fecha_cierre"] == "2026-09-05 14:30"
    assert fila["tiempo_resolucion_horas"] == "4.5"
    assert fila["cierre_aproximado"] == ""


def test_fila_tiene_exactamente_las_columnas_definidas():
    assert set(construir_fila(conversacion(), MENSAJES, MAPEO)) == set(COLUMNAS)


def test_fila_de_conversacion_abierta():
    fila = construir_fila(conversacion(status="open"), MENSAJES, MAPEO)
    assert fila["estado"] == "abierta"
    assert fila["fecha_cierre"] == ""
    assert fila["tiempo_resolucion_horas"] == ""


def test_fila_sin_asesor_asignado():
    fila = construir_fila(conversacion(meta={}), MENSAJES, MAPEO)
    assert fila["asesor"] == ""
    assert fila["email_asesor"] == ""
    assert fila["area"] == "SIN_ASIGNAR"


def test_fila_con_asesor_sin_mapear():
    conv = conversacion(meta={"assignee": {"name": "Nuevo", "email": "n@empresa.com"}})
    assert construir_fila(conv, MENSAJES, MAPEO)["area"] == "SIN_MAPEAR"


def test_fila_sin_etiquetas():
    assert construir_fila(conversacion(labels=[]), MENSAJES, MAPEO)["etiquetas"] == ""


def test_fila_marca_el_cierre_aproximado():
    fila = construir_fila(conversacion(), [mensaje(1, 0, "hola")], MAPEO)
    assert fila["cierre_aproximado"] == "Sí"


def test_csv_lleva_bom_y_encabezados_en_espanol():
    contenido = escribir_csv([construir_fila(conversacion(), MENSAJES, MAPEO)])
    assert contenido.startswith(b"\xef\xbb\xbf")
    texto = contenido.decode("utf-8-sig")
    assert texto.splitlines()[0] == ",".join(COLUMNAS)
    assert "Ana Pérez" in texto


def test_csv_vacio_conserva_los_encabezados():
    texto = escribir_csv([]).decode("utf-8-sig")
    assert texto.strip() == ",".join(COLUMNAS)


def test_nombre_del_archivo():
    assert (
        nombre_archivo(date(2026, 9, 1), date(2026, 9, 30))
        == "reporte-chatwoot-2026-09-01-a-2026-09-30.csv"
    )


class ClienteFalso:
    def __init__(self, conversaciones, mensajes_por_id):
        self.conversaciones = conversaciones
        self.mensajes_por_id = mensajes_por_id
        self.pedidos = []

    def listar_conversaciones(self, desde, hasta):
        return self.conversaciones

    def listar_mensajes(self, conversacion_id):
        self.pedidos.append(conversacion_id)
        return self.mensajes_por_id[conversacion_id]


def test_generar_filas_recorre_todas_las_conversaciones():
    cliente = ClienteFalso([conversacion(), conversacion(id=102)], {101: MENSAJES, 102: MENSAJES})
    filas = generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO)
    assert [f["conversacion_id"] for f in filas] == ["101", "102"]


def test_generar_filas_informa_el_progreso():
    cliente = ClienteFalso([conversacion(), conversacion(id=102)], {101: MENSAJES, 102: MENSAJES})
    avances = []
    generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO, al_avanzar=lambda h, t: avances.append((h, t)))
    assert avances == [(1, 2), (2, 2)]


def test_generar_filas_usa_la_cache_de_conversaciones_resueltas(tmp_path: Path):
    from chatwoot import CacheMensajes

    cache = CacheMensajes(tmp_path)
    cache.guardar(101, MENSAJES)
    cliente = ClienteFalso([conversacion()], {})
    filas = generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO, cache=cache)
    assert cliente.pedidos == []
    assert filas[0]["direccion"] == "Entrante"


def test_generar_filas_no_cachea_conversaciones_abiertas(tmp_path: Path):
    from chatwoot import CacheMensajes

    cache = CacheMensajes(tmp_path)
    cliente = ClienteFalso([conversacion(status="open")], {101: MENSAJES})
    generar_filas(cliente, DESDE_FECHA, HASTA_FECHA, MAPEO, cache=cache)
    assert cache.leer(101) is None
```

Agregar cerca de las constantes del archivo de test:

```python
DESDE_FECHA = datetime(2026, 9, 1, 0, 0, tzinfo=TZ)
HASTA_FECHA = datetime(2026, 9, 30, 23, 59, tzinfo=TZ)
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `python -m pytest tests/test_reporte.py -v`
Expected: FAIL con `ImportError: cannot import name 'COLUMNAS'`

- [ ] **Step 3: Escribir la implementación**

Agregar a `reporte.py` los imports `io` y `from datetime import date`, y luego:

```python
COLUMNAS = (
    "conversacion_id",
    "asesor",
    "email_asesor",
    "area",
    "fecha_creacion",
    "etiquetas",
    "direccion",
    "estado",
    "fecha_cierre",
    "tiempo_resolucion_horas",
    "cierre_aproximado",
)

FORMATO_FECHA = "%Y-%m-%d %H:%M"


def _texto_fecha(momento: datetime | None) -> str:
    return momento.strftime(FORMATO_FECHA) if momento else ""


def construir_fila(
    conversacion: dict, mensajes: list[dict], mapeo: dict[str, str]
) -> dict[str, str]:
    asignado = (conversacion.get("meta") or {}).get("assignee") or {}
    email = asignado.get("email") or ""
    creacion = a_fecha_local(conversacion.get("created_at"))
    cierre, aproximado = detectar_cierre(conversacion, mensajes)

    if cierre and creacion:
        horas = f"{(cierre - creacion).total_seconds() / 3600:.1f}"
    else:
        horas = ""

    return {
        "conversacion_id": str(conversacion.get("id", "")),
        "asesor": asignado.get("name") or "",
        "email_asesor": email,
        "area": resolver_area(email, mapeo),
        "fecha_creacion": _texto_fecha(creacion),
        "etiquetas": ";".join(conversacion.get("labels") or []),
        "direccion": detectar_direccion(mensajes),
        "estado": traducir_estado(conversacion.get("status", "")),
        "fecha_cierre": _texto_fecha(cierre),
        "tiempo_resolucion_horas": horas,
        "cierre_aproximado": "Sí" if cierre and aproximado else "",
    }


def generar_filas(
    cliente,
    desde: datetime,
    hasta: datetime,
    mapeo: dict[str, str],
    cache=None,
    al_avanzar=None,
) -> list[dict[str, str]]:
    """Trae las conversaciones del rango y arma una fila por cada una."""
    conversaciones = cliente.listar_conversaciones(desde, hasta)
    total = len(conversaciones)
    filas = []

    for indice, conversacion in enumerate(conversaciones, start=1):
        conversacion_id = conversacion["id"]
        resuelta = conversacion.get("status") == "resolved"

        mensajes = cache.leer(conversacion_id) if cache and resuelta else None
        if mensajes is None:
            mensajes = cliente.listar_mensajes(conversacion_id)
            # Solo se cachean las resueltas: las abiertas todavía pueden cambiar.
            if cache and resuelta:
                cache.guardar(conversacion_id, mensajes)

        filas.append(construir_fila(conversacion, mensajes, mapeo))
        if al_avanzar:
            al_avanzar(indice, total)

    return filas


def escribir_csv(filas: list[dict[str, str]]) -> bytes:
    """CSV con BOM para que Excel en Windows respete los acentos."""
    memoria = io.StringIO()
    escritor = csv.DictWriter(memoria, fieldnames=list(COLUMNAS), lineterminator="\r\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return memoria.getvalue().encode("utf-8-sig")


def nombre_archivo(desde: date, hasta: date) -> str:
    return f"reporte-chatwoot-{desde:%Y-%m-%d}-a-{hasta:%Y-%m-%d}.csv"
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `python -m pytest -v`
Expected: PASS, todos los tests de las cuatro tareas anteriores incluidos.

- [ ] **Step 5: Commit**

```bash
git add reporte.py tests/test_reporte.py
git commit -m "Armar las filas del reporte y escribir el CSV"
```

---

### Task 7: Interfaz web con login

**Files:**
- Create: `app.py`
- Create: `generar_hash.py`

**Interfaces:**
- Consumes: `cargar_config`, `ConfigError`, `ruta_asesores`, `ruta_cache`
  (Tarea 1); `ClienteChatwoot`, `CacheMensajes`, `ChatwootError` (Tareas 2-3);
  `cargar_asesores`, `guardar_asesores`, `generar_filas`, `escribir_csv`,
  `nombre_archivo`, `AREAS_VALIDAS`, `SIN_MAPEAR`, `TZ` (Tareas 4-6).
- Produces: la aplicación ejecutable. Nada consume esto.

Esta tarea no lleva tests automatizados: es una interfaz, y el núcleo que sí
tiene lógica ya quedó cubierto. La verificación es manual, en el Paso 4.

- [ ] **Step 1: Crear el generador de hash de contraseña**

Crear `generar_hash.py`:

```python
"""Genera el hash bcrypt para la variable APP_PASSWORD_HASH.

Uso: python generar_hash.py 'la-contraseña-elegida'
"""

import sys

import bcrypt

if len(sys.argv) != 2:
    print("Uso: python generar_hash.py 'la-contraseña'")
    raise SystemExit(1)

hash_generado = bcrypt.hashpw(sys.argv[1].encode("utf-8"), bcrypt.gensalt())
print(hash_generado.decode("utf-8"))
```

- [ ] **Step 2: Crear la aplicación**

Crear `app.py`:

```python
"""Interfaz web del reporte de conversaciones de Chatwoot."""

import os
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth

from chatwoot import CacheMensajes, ChatwootError, ClienteChatwoot
from config import ConfigError, cargar_config, ruta_asesores, ruta_cache
from reporte import (
    AREAS_VALIDAS,
    SIN_MAPEAR,
    TZ,
    cargar_asesores,
    escribir_csv,
    generar_filas,
    guardar_asesores,
    nombre_archivo,
)

DIAS_RANGO_AMPLIO = 90

st.set_page_config(page_title="Reporte de Chatwoot", page_icon="📊")


@st.cache_resource
def obtener_config():
    return cargar_config(os.environ)


try:
    CFG = obtener_config()
except ConfigError as error:
    st.error(f"La aplicación no está bien configurada.\n\n{error}")
    st.stop()

autenticador = stauth.Authenticate(
    {
        "usernames": {
            CFG.usuario: {
                "name": CFG.usuario,
                "password": CFG.password_hash,
                "email": "",
            }
        }
    },
    "reporte_chatwoot",
    CFG.cookie_key,
    cookie_expiry_days=7,
)

autenticador.login(location="main", fields={"Form name": "Ingresar"})

if st.session_state.get("authentication_status") is False:
    st.error("Usuario o contraseña incorrectos.")
    st.stop()
if st.session_state.get("authentication_status") is None:
    st.info("Ingrese sus datos para ver el reporte.")
    st.stop()

autenticador.logout("Cerrar sesión", "sidebar")
st.title("Reporte de conversaciones de Chatwoot")

pestana_reporte, pestana_asesores = st.tabs(["Reporte", "Asesores"])
```

- [ ] **Step 3: Agregar la pestaña Reporte a `app.py`**

```python
with pestana_reporte:
    hoy = date.today()
    columna_desde, columna_hasta = st.columns(2)
    desde = columna_desde.date_input("Desde", value=hoy.replace(day=1), format="YYYY-MM-DD")
    hasta = columna_hasta.date_input("Hasta", value=hoy, format="YYYY-MM-DD")

    if desde > hasta:
        st.warning("La fecha inicial no puede ser posterior a la final.")
    elif (hasta - desde) > timedelta(days=DIAS_RANGO_AMPLIO):
        st.info(
            f"El rango supera {DIAS_RANGO_AMPLIO} días. La consulta puede tardar "
            "varios minutos la primera vez."
        )

    if st.button("Generar reporte", type="primary", disabled=desde > hasta):
        cliente = ClienteChatwoot(CFG.base_url, CFG.account_id, CFG.api_token)
        mapeo = cargar_asesores(ruta_asesores(CFG))
        barra = st.progress(0.0, text="Consultando conversaciones…")

        def avanzar(hechas: int, total: int) -> None:
            barra.progress(hechas / total, text=f"Procesando {hechas} de {total}…")

        try:
            filas = generar_filas(
                cliente,
                datetime.combine(desde, time.min, tzinfo=TZ),
                datetime.combine(hasta, time.max, tzinfo=TZ),
                mapeo,
                cache=CacheMensajes(ruta_cache(CFG)),
                al_avanzar=avanzar,
            )
        except ChatwootError as error:
            barra.empty()
            st.error(f"No se pudo consultar Chatwoot.\n\n{error}")
            st.stop()

        barra.empty()

        if not filas:
            st.warning("No hay conversaciones en el rango seleccionado.")
            st.stop()

        sin_mapear = sorted(
            {f["email_asesor"] for f in filas if f["area"] == SIN_MAPEAR}
        )
        if sin_mapear:
            st.warning(
                "Estos asesores no tienen área asignada. Agréguelos en la pestaña "
                "Asesores: " + ", ".join(sin_mapear)
            )

        st.success(f"{len(filas)} conversaciones encontradas.")
        st.dataframe(pd.DataFrame(filas), use_container_width=True)
        st.download_button(
            "Descargar CSV",
            data=escribir_csv(filas),
            file_name=nombre_archivo(desde, hasta),
            mime="text/csv",
        )
```

- [ ] **Step 4: Agregar la pestaña Asesores a `app.py`**

```python
with pestana_asesores:
    st.caption(
        "Cada asesor pertenece a un área. Los asesores que no estén en esta lista "
        "aparecen como SIN_MAPEAR en el reporte."
    )

    actual = cargar_asesores(ruta_asesores(CFG))
    tabla = pd.DataFrame(
        sorted(actual.items()) or [], columns=["email_asesor", "area"]
    )

    editada = st.data_editor(
        tabla,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "email_asesor": st.column_config.TextColumn("Correo del asesor", required=True),
            "area": st.column_config.SelectboxColumn(
                "Área", options=list(AREAS_VALIDAS), required=True
            ),
        },
        key="editor_asesores",
    )

    if st.button("Guardar cambios", type="primary"):
        limpias = [
            (str(fila.email_asesor).strip().lower(), str(fila.area).strip())
            for fila in editada.itertuples()
            if str(fila.email_asesor).strip()
        ]
        correos = [correo for correo, _ in limpias]
        invalidas = [area for _, area in limpias if area not in AREAS_VALIDAS]

        if len(correos) != len(set(correos)):
            st.error("Hay correos repetidos. Cada asesor debe aparecer una sola vez.")
        elif invalidas:
            st.error(f"El área debe ser {' o '.join(AREAS_VALIDAS)}.")
        else:
            guardar_asesores(ruta_asesores(CFG), dict(limpias))
            st.success(f"Se guardaron {len(limpias)} asesores.")
```

Agregar `pandas==2.2.3` a `requirements.txt` (Streamlit ya lo trae como
dependencia, pero se fija la versión de forma explícita porque el código lo
importa directamente).

- [ ] **Step 5: Confirmar la firma de `login()`**

`streamlit-authenticator` cambió la firma de `Authenticate.login()` entre
versiones menores. Con la versión fijada en `requirements.txt` instalada:

```bash
python -c "import streamlit_authenticator as s, inspect; print(inspect.signature(s.Authenticate.login))"
```

Si los parámetros no son `location` y `fields`, ajustar la llamada en `app.py`
a la firma que reporte el comando. Lo que no cambia: el estado queda en
`st.session_state['authentication_status']`.

- [ ] **Step 6: Verificar la aplicación localmente**

```bash
python generar_hash.py 'prueba123'
```

Exportar las variables con ese hash, `DATA_DIR=./data-local`, y las credenciales
reales de Chatwoot. Luego:

```bash
streamlit run app.py
```

Comprobar en el navegador, en orden: (1) sin ingresar credenciales no se ve
ninguna pestaña; (2) una contraseña incorrecta muestra el error; (3) con la
contraseña correcta aparecen las dos pestañas; (4) al recargar la página la
sesión sigue abierta; (5) generar un reporte de tres días muestra la tabla y
descarga el CSV; (6) el CSV abre en Excel con los acentos correctos; (7) agregar
un asesor en la segunda pestaña y volver a generar el reporte cambia su área.

- [ ] **Step 7: Commit**

```bash
git add app.py generar_hash.py requirements.txt
git commit -m "Agregar interfaz web con login, reporte y edición de asesores"
```

---

### Task 8: Empaquetado en Docker y despliegue en EasyPanel

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `README.md`

**Interfaces:**
- Consumes: todo el código anterior.
- Produces: imagen desplegable. Nada consume esto.

- [ ] **Step 1: Crear `.dockerignore`**

```
.git
.gitignore
.env
data
data-local
tests
__pycache__
*.pyc
.venv
docs
README.md
```

- [ ] **Step 2: Crear el `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Bogota \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py chatwoot.py reporte.py app.py generar_hash.py ./

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
```

- [ ] **Step 3: Probar la imagen localmente**

```bash
docker build -t reporte-chatwoot .
```

```bash
docker run --rm -p 8501:8501 --env-file .env -v "$PWD/data-local:/data" reporte-chatwoot
```

Abrir `http://localhost:8501` y repetir la comprobación del Paso 5 de la Tarea
7. Luego detener el contenedor, volverlo a levantar y confirmar que **el mapeo
de asesores sigue ahí** — esa es la prueba de que el volumen funciona, y es lo
que evita perder la configuración en cada redespliegue de EasyPanel.

- [ ] **Step 4: Escribir el `README.md`**

````markdown
# Reporte de conversaciones de Chatwoot

Aplicación web que genera, para el rango de fechas que se elija, un CSV con las
conversaciones de Chatwoot: asesor, fecha, etiquetas, tiempo de resolución, si
fue entrante o saliente, fecha de cierre y área (Comercial o RDC).

## Uso

Se entra con usuario y contraseña. Hay dos pestañas:

- **Reporte**: elegir *Desde* y *Hasta*, presionar *Generar reporte* y descargar
  el CSV.
- **Asesores**: mantener la lista de correo → área. Un asesor que no esté en la
  lista aparece como `SIN_MAPEAR` en el reporte.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `CHATWOOT_BASE_URL` | Ej. `https://chat.miempresa.com` |
| `CHATWOOT_ACCOUNT_ID` | Id numérico de la cuenta |
| `CHATWOOT_API_TOKEN` | Token de acceso de un usuario administrador |
| `APP_USERNAME` | Usuario del login |
| `APP_PASSWORD_HASH` | Hash bcrypt de la contraseña |
| `APP_COOKIE_KEY` | Cadena aleatoria para firmar la cookie de sesión |
| `DATA_DIR` | Ruta de los datos persistentes (por defecto `/data`) |
| `TZ` | `America/Bogota` |

Para generar el hash de la contraseña:

```bash
python generar_hash.py 'la-contraseña-elegida'
```

## Despliegue en EasyPanel

1. Crear un servicio de tipo App apuntando a este repositorio (usa el
   `Dockerfile`).
2. **Montar un volumen persistente en `/data`.** Sin esto se pierden el mapeo de
   asesores y la caché en cada despliegue.
3. Cargar las variables de entorno de la tabla anterior.
4. Asignar el dominio. EasyPanel gestiona el HTTPS.

## Desarrollo

```bash
pip install -r requirements.txt
python -m pytest
streamlit run app.py
```

## Nota sobre la fecha de cierre

La API de Chatwoot no expone un campo de fecha de cierre por conversación. La
fecha se deduce del evento de resolución en el hilo de mensajes. Cuando ese
evento no se puede identificar, se usa la última actividad como aproximación y
la fila queda marcada con `cierre_aproximado = Sí`. El detalle está en la
sección 5.3 de `docs/superpowers/specs/2026-09-07-reporte-chatwoot-design.md`.
````

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore README.md
git commit -m "Empaquetar la aplicación en Docker para EasyPanel"
```

---

### Task 9: Verificación contra la instancia real

**Files:** ninguno, salvo correcciones que surjan.

Esta tarea existe porque los tests usan respuestas simuladas. El detalle más
frágil es el formato exacto del filtro `created_at` en
`POST /conversations/filter`: Chatwoot ha cambiado entre versiones si espera
epoch o una fecha en texto. Nada de eso se descubre sin la instancia real.

- [ ] **Step 1: Generar un reporte de un solo día conocido**

Elegir un día con pocas conversaciones y generarlo desde la app.

- [ ] **Step 2: Comparar el conteo contra Chatwoot**

En la interfaz de Chatwoot, filtrar por ese mismo día y contar. Debe coincidir
con la cantidad de filas del CSV.

Si no coincide, el filtro de fecha es el sospechoso: revisar
`listar_conversaciones` en `chatwoot.py` y probar enviando la fecha como texto
`YYYY-MM-DD` en lugar de epoch. Ajustar el test
`test_envia_el_token_y_el_rango_de_fechas` para que refleje el formato correcto.

- [ ] **Step 3: Verificar tres conversaciones a mano**

Tomar del CSV una conversación entrante, una saliente y una resuelta. Abrir cada
una en Chatwoot y confirmar que la dirección, el asesor, las etiquetas y la
fecha de cierre coinciden. Revisar cuántas filas quedaron con
`cierre_aproximado = Sí`: si son muchas, el idioma de las actividades no está
cubierto por `_PATRON_RESOLUCION` — copiar el texto real de la actividad de
resolución y ampliar la expresión regular, con un test nuevo que lo cubra.

- [ ] **Step 4: Confirmar el rendimiento**

Generar un mes completo y medir cuánto tarda. Repetir la misma consulta y
confirmar que la segunda vez es mucho más rápida — eso demuestra que la caché
está funcionando.

- [ ] **Step 5: Commit de los ajustes**

```bash
git add -A
git commit -m "Ajustar el cliente según el comportamiento real de la API"
```
