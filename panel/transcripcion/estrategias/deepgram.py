"""Estrategia de Deepgram: `POST /v1/listen` con el audio en el cuerpo.

Deepgram devuelve el texto partido en frases (`utterances`) con sus tiempos y,
con `diarize`, un número de hablante por frase (0, 1…), que aquí pasa a ser la
etiqueta «A», «B»… como en el resto de los proveedores. Un canal de un estéreo
ya es de una sola persona: se pide sin separar hablantes.

El vocabulario va como `keyterm` en Nova-3 y como `keywords` en los modelos
anteriores. Si Deepgram rechaza el pedido por eso (un modelo o idioma que no
lo admite), se repite una vez sin vocabulario.

Las cuentas nuevas traen crédito gratis; el precio por minuto se carga en
Transcripción › Configuración como en cualquier modelo.
"""

import logging
import math
import time
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from string import ascii_uppercase
from urllib.parse import parse_qs, urlparse

import requests

from panel.transcripcion.base import (
    AudioPreparado,
    Capacidades,
    CobroInformado,
    OpcionesTranscripcion,
    Segmento,
    Transcripcion,
    TranscripcionError,
    TranscripcionNoDisponible,
)
from panel.transcripcion.registro import registrar

URL_POR_DEFECTO = "https://api.deepgram.com/v1"
MODELO_POR_DEFECTO = "nova-3"
# `diarize_model` reemplaza al `diarize=true` obsoleto. Para audios grabados,
# «latest» es hoy el diarizador v2 (SDK oficial de Deepgram).
DIARIZADOR_POR_DEFECTO = "latest"
TIEMPO_LIMITE_SEGUNDOS = 600
INTENTOS_MAXIMOS = 3
ESPERA_BASE_SEGUNDOS = 2.0
ESPERA_MAXIMA_SEGUNDOS = 60.0
registro = logging.getLogger(__name__)

# Pedidos por página al leer el historial de pedidos (y un tope de páginas).
PEDIDOS_POR_PAGINA = 1000
PAGINAS_MAXIMAS = 200
# Deepgram acepta archivos de hasta 2 GB: una llamada nunca llega.
CAPACIDADES = Capacidades(diarizacion=True, marcas_de_tiempo=True, tamano_max_bytes=None)


def _decimal(texto: str | None) -> Decimal | None:
    if not (texto or "").strip():
        return None
    try:
        return Decimal(texto.strip().replace(",", "."))
    except InvalidOperation as error:
        raise TranscripcionNoDisponible(f"DEEPGRAM_PRECIO_MINUTO no es un número: {texto!r}") from error


def _etiqueta(hablante) -> str | None:
    """0 → «A», 1 → «B»… (más allá de la Z, el número)."""
    try:
        numero = int(hablante)
    except (TypeError, ValueError):
        return None
    return ascii_uppercase[numero] if 0 <= numero < len(ascii_uppercase) else str(numero)


def _numero(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


# Una pausa más larga que esto abre otra frase aunque siga la misma voz.
PAUSA_NUEVA_FRASE_S = 1.5


def _segmentos_por_palabra(resultados: dict) -> list[Segmento]:
    """Las frases armadas con el hablante de cada palabra.

    Deepgram da un solo hablante por `utterance`, y una utterance se corta por
    pausas: en una llamada donde agente y cliente hablan sin pausa, una sola
    utterance mezcla las dos voces y queda entera a nombre de una. Cada
    palabra, en cambio, trae su hablante: se agrupan las seguidas de la misma
    voz. Si hay una sola voz, se corta además en cada oración. Vacío si las
    palabras no traen hablante (entonces valen las utterances)."""
    # Las palabras de las utterances traen `punctuated_word` (con mayúsculas y
    # signos); las del canal no (tipos del SDK oficial de Deepgram). Se usan
    # las del canal solo si no hay utterances.
    palabras = [p for u in resultados.get("utterances") or [] for p in u.get("words") or []]
    if not palabras:
        canales = resultados.get("channels") or [{}]
        alternativas = canales[0].get("alternatives") or [{}]
        palabras = alternativas[0].get("words") or []
    if not palabras or all(p.get("speaker") is None for p in palabras):
        return []
    # Si Deepgram oyó una sola voz, cada oración va aparte: así el auditor
    # puede marcar quién dijo cada una (un bloque mezclaría a los dos).
    una_sola_voz = len({p.get("speaker") for p in palabras}) == 1
    segmentos: list[Segmento] = []
    actual: dict | None = None

    def cerrar():
        if actual and actual["textos"]:
            segmentos.append(Segmento(
                hablante="desconocido", etiqueta=actual["etiqueta"], inicio=actual["inicio"],
                fin=actual["fin"], texto=" ".join(actual["textos"]),
            ))

    for palabra in palabras:
        texto = str(palabra.get("punctuated_word") or palabra.get("word") or "").strip()
        if not texto:
            continue
        etiqueta = _etiqueta(palabra.get("speaker"))
        inicio, fin = _numero(palabra.get("start")), _numero(palabra.get("end"))
        pausa = (inicio - actual["fin"]) if actual and inicio is not None and actual["fin"] is not None else 0
        if actual is None or etiqueta != actual["etiqueta"] or pausa > PAUSA_NUEVA_FRASE_S:
            cerrar()
            actual = {"etiqueta": etiqueta, "inicio": inicio, "fin": fin, "textos": []}
        actual["textos"].append(texto)
        actual["fin"] = fin if fin is not None else actual["fin"]
        if una_sola_voz and texto[-1] in ".?!…":
            cerrar()
            actual = None
    cerrar()
    return segmentos


def _url(valores: Mapping[str, str]) -> str:
    return (valores.get("DEEPGRAM_BASE_URL") or URL_POR_DEFECTO).strip().rstrip("/")


def _cabeceras(clave: str) -> dict[str, str]:
    return {"Authorization": f"Token {clave}"}


@registrar
class EstrategiaDeepgram:
    nombre = "deepgram"
    titulo = "Deepgram"
    variable_clave = "DEEPGRAM_API_KEY"
    variables_modelo = ("DEEPGRAM_MODELO_TRANSCRIPCION", "DEEPGRAM_PRECIO_MINUTO", "DEEPGRAM_REDONDEO")
    modelos_conocidos = {"nova-3": CAPACIDADES, "nova-2": CAPACIDADES}
    # Todos los modelos de Deepgram separan hablantes y dan tiempos.
    capacidades_por_defecto = CAPACIDADES

    def __init__(
        self,
        clave: str,
        modelo: str = MODELO_POR_DEFECTO,
        precio_minuto: Decimal | None = None,
        url: str = URL_POR_DEFECTO,
        sesion: requests.Session | None = None,
        redondeo: str = "segundo",
        diarizador: str = DIARIZADOR_POR_DEFECTO,
    ) -> None:
        self._clave = clave
        self._modelo = modelo
        self._diarizador = diarizador
        self._precio = precio_minuto
        self._redondeo_minuto = redondeo == "minuto"
        self._url = url.rstrip("/")
        self._sesion = sesion or requests.Session()

    @classmethod
    def desde_config(cls, valores: Mapping[str, str]) -> "EstrategiaDeepgram":
        clave = (valores.get("DEEPGRAM_API_KEY") or "").strip()
        if not clave:
            raise TranscripcionNoDisponible("Falta DEEPGRAM_API_KEY.")
        return cls(
            clave=clave,
            modelo=(valores.get("DEEPGRAM_MODELO_TRANSCRIPCION") or MODELO_POR_DEFECTO).strip(),
            precio_minuto=_decimal(valores.get("DEEPGRAM_PRECIO_MINUTO")),
            url=_url(valores),
            redondeo=(valores.get("DEEPGRAM_REDONDEO") or "segundo").strip(),
            diarizador=(valores.get("DEEPGRAM_DIARIZADOR") or DIARIZADOR_POR_DEFECTO).strip(),
        )

    @classmethod
    def probar_clave(cls, valores: Mapping[str, str]) -> str:
        """Pide los proyectos de la cuenta (y su saldo): no transcribe ni cuesta."""
        clave = (valores.get("DEEPGRAM_API_KEY") or "").strip()
        if not clave:
            raise TranscripcionNoDisponible("Falta la clave de Deepgram.")
        url = _url(valores)
        try:
            respuesta = requests.get(f"{url}/projects", headers=_cabeceras(clave), timeout=20)
        except requests.RequestException as error:
            raise TranscripcionError(f"No se pudo conectar con Deepgram: {error}") from error
        if respuesta.status_code in (401, 403):
            raise TranscripcionError("Deepgram rechazó la clave.")
        if respuesta.status_code >= 400:
            raise TranscripcionError(f"Deepgram respondió {respuesta.status_code}.")
        proyectos = respuesta.json().get("projects") or []
        saldo = cls._saldo(url, clave, proyectos)
        return "Clave válida." + (f" Saldo de la cuenta: {saldo}." if saldo else "")

    @classmethod
    def listar_modelos(cls, valores: Mapping[str, str], idioma: str) -> list[str]:
        """`GET /v1/models`: los de voz a texto que sirven para audios grabados
        y entienden el idioma (o son multilingües). Los Nova-3 primero."""
        clave = (valores.get("DEEPGRAM_API_KEY") or "").strip()
        if not clave:
            raise TranscripcionNoDisponible("Falta la clave de Deepgram.")
        try:
            respuesta = requests.get(f"{_url(valores)}/models", headers=_cabeceras(clave), timeout=20)
        except requests.RequestException as error:
            raise TranscripcionError("No se pudo conectar con Deepgram.") from error
        if respuesta.status_code in (401, 403):
            raise TranscripcionError("Deepgram rechazó la clave.")
        if respuesta.status_code >= 400:
            raise TranscripcionError(f"Deepgram respondió {respuesta.status_code}.")
        idioma = idioma.strip().lower()
        modelos = set()
        for modelo in respuesta.json().get("stt") or []:
            if modelo.get("batch") is False:
                continue
            idiomas = [str(i).lower() for i in modelo.get("languages") or []]
            if idioma and idiomas and not any(i == "multi" or i.split("-")[0] == idioma for i in idiomas):
                continue
            nombre = modelo.get("canonical_name") or modelo.get("name")
            if nombre:
                modelos.add(str(nombre))
        return sorted(modelos, key=lambda m: (not m.startswith("nova-3"), not m.startswith("nova-2"), m))

    @classmethod
    def cobros(cls, valores: Mapping[str, str], desde: datetime, hasta: datetime) -> list[CobroInformado]:
        """Lo cobrado por modelo en [desde, hasta), sumando el historial de
        pedidos de cada proyecto (`GET /projects/{id}/requests`): cada
        transcripción trae su costo (`usd`) y su duración. El modelo sale del
        `model=` con que se pidió."""
        clave = (valores.get("DEEPGRAM_API_KEY") or "").strip()
        if not clave:
            raise TranscripcionNoDisponible("Falta la clave de Deepgram.")
        url = _url(valores)
        segundos: dict[str, Decimal] = defaultdict(Decimal)
        usd: dict[str, Decimal] = defaultdict(Decimal)
        transcripciones = con_costo = 0
        for proyecto in cls._json(url, clave, "/projects").get("projects") or []:
            for pedido in cls._pedidos(url, clave, proyecto.get("project_id"), desde, hasta):
                ruta = pedido.get("path") or ""
                if "/listen" not in ruta:
                    continue
                transcripciones += 1
                detalles = (pedido.get("response") or {}).get("details") or {}
                costo, duracion = _numero(detalles.get("usd")), _numero(detalles.get("duration"))
                if costo is None:
                    continue
                con_costo += 1
                modelo = (parse_qs(urlparse(ruta).query).get("model") or ["sin modelo"])[0]
                usd[modelo] += Decimal(str(costo))
                segundos[modelo] += Decimal(str(duracion or 0))
        if transcripciones and not con_costo:
            raise TranscripcionError(
                "Deepgram no informó el costo de las transcripciones: cargue lo cobrado a mano."
            )
        return [
            CobroInformado(
                modelo=modelo,
                minutos=(segundos[modelo] / 60).quantize(Decimal("0.01")),
                usd=usd[modelo].quantize(Decimal("0.0001")),
            )
            for modelo in sorted(usd)
        ]

    @classmethod
    def _pedidos(cls, url: str, clave: str, proyecto: str | None, desde: datetime, hasta: datetime):
        if not proyecto:
            return
        utc = lambda momento: momento.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        for pagina in range(PAGINAS_MAXIMAS):
            datos = cls._json(url, clave, f"/projects/{proyecto}/requests", {
                "start": utc(desde), "end": utc(hasta), "status": "succeeded",
                "limit": PEDIDOS_POR_PAGINA, "page": pagina,
            })
            pedidos = datos.get("requests") or []
            yield from pedidos
            if len(pedidos) < PEDIDOS_POR_PAGINA:
                return

    @staticmethod
    def _json(url: str, clave: str, ruta: str, parametros: dict | None = None) -> dict:
        try:
            respuesta = requests.get(f"{url}{ruta}", params=parametros, headers=_cabeceras(clave), timeout=30)
        except requests.RequestException as error:
            raise TranscripcionError("No se pudo conectar con Deepgram.") from error
        if respuesta.status_code in (401, 403):
            raise TranscripcionError(
                "Deepgram no deja ver el uso con esta clave: hace falta una clave con permiso de "
                "administrador o miembro del proyecto."
            )
        if respuesta.status_code >= 400:
            raise TranscripcionError(f"Deepgram respondió {respuesta.status_code}: {respuesta.text[:200]}")
        try:
            return respuesta.json()
        except ValueError as error:
            raise TranscripcionError("Deepgram respondió algo que no es JSON.") from error

    @staticmethod
    def _saldo(url: str, clave: str, proyectos: list[dict]) -> str:
        """El crédito que queda, si la clave puede verlo. Vacío si no."""
        partes = []
        for proyecto in proyectos:
            try:
                respuesta = requests.get(
                    f"{url}/projects/{proyecto.get('project_id')}/balances",
                    headers=_cabeceras(clave), timeout=20,
                )
                if respuesta.status_code >= 400:
                    continue
                for saldo in respuesta.json().get("balances") or []:
                    monto = _numero(saldo.get("amount"))
                    if monto is not None:
                        partes.append(f"{monto:.2f} {(saldo.get('units') or 'usd').upper()}")
            except (requests.RequestException, ValueError):
                continue
        return ", ".join(partes)

    @property
    def modelo(self) -> str:
        return self._modelo

    @property
    def capacidades(self) -> Capacidades:
        return CAPACIDADES

    def costo_estimado(self, duracion_s: float | None) -> Decimal | None:
        if self._precio is None or duracion_s is None:
            return None
        minutos = Decimal(str(duracion_s)) / 60
        if self._redondeo_minuto:
            minutos = Decimal(math.ceil(minutos))
        return (self._precio * minutos).quantize(Decimal("0.0001"))

    # --- Petición ------------------------------------------------------------

    def _parametros(
        self, audio: AudioPreparado, opciones: OpcionesTranscripcion, vocabulario: bool, diarizador: bool = True
    ):
        parametros = [
            ("model", self._modelo),
            ("language", opciones.idioma),
            ("punctuate", "true"),
            ("smart_format", "true"),
            ("utterances", "true"),
        ]
        # Un canal de un estéreo ya es de una sola persona: no se separan voces.
        if audio.hablante is None:
            parametros.append(("diarize_model", self._diarizador) if diarizador else ("diarize", "true"))
        if vocabulario:
            nombre = "keyterm" if self._modelo.startswith("nova-3") else "keywords"
            parametros += [(nombre, palabra) for palabra in opciones.vocabulario]
        return parametros

    def _enviar(self, audio: AudioPreparado, opciones: OpcionesTranscripcion) -> dict:
        vocabulario = bool(opciones.vocabulario)
        diarizador = True
        ultimo_error = ""
        for intento in range(INTENTOS_MAXIMOS):
            try:
                respuesta = self._sesion.post(
                    f"{self._url}/listen",
                    params=self._parametros(audio, opciones, vocabulario, diarizador),
                    headers={**_cabeceras(self._clave), "Content-Type": audio.tipo_mime},
                    data=audio.contenido,
                    timeout=TIEMPO_LIMITE_SEGUNDOS,
                )
            except requests.RequestException as error:
                ultimo_error = str(error)
                time.sleep(ESPERA_BASE_SEGUNDOS * (2**intento))
                continue

            if respuesta.status_code in (401, 403):
                raise TranscripcionError("Deepgram rechazó la clave. Revise DEEPGRAM_API_KEY.")
            if respuesta.status_code == 402:
                raise TranscripcionError("Deepgram: la cuenta no tiene saldo.")
            if respuesta.status_code < 400:
                return respuesta.json()
            if respuesta.status_code == 400 and diarizador and "diariz" in respuesta.text.lower():
                # Una cuenta o región que todavía no acepta `diarize_model`:
                # se pide con el `diarize=true` de antes.
                registro.warning("Deepgram rechazó diarize_model, se usa diarize=true: %s", respuesta.text[:200])
                diarizador = False
                ultimo_error = f"HTTP 400: {respuesta.text[:200]}"
                continue
            if respuesta.status_code == 400 and vocabulario:
                # Un modelo o idioma que no admite el vocabulario: se pide sin él.
                vocabulario = False
                ultimo_error = f"HTTP 400: {respuesta.text[:200]}"
                continue
            if respuesta.status_code == 429 or respuesta.status_code >= 500:
                ultimo_error = f"HTTP {respuesta.status_code}: {respuesta.text[:200]}"
                time.sleep(self._espera(respuesta, intento))
                continue
            raise TranscripcionError(f"Deepgram respondió {respuesta.status_code}: {respuesta.text[:300]}")
        raise TranscripcionError(f"Deepgram no respondió tras {INTENTOS_MAXIMOS} intentos ({ultimo_error}).")

    @staticmethod
    def _espera(respuesta: requests.Response, intento: int) -> float:
        try:
            espera = float(respuesta.headers.get("Retry-After", ""))
        except ValueError:
            espera = ESPERA_BASE_SEGUNDOS * (2**intento)
        return max(0.0, min(espera, ESPERA_MAXIMA_SEGUNDOS))

    # --- Traducción a la forma común -----------------------------------------

    def transcribir(self, audio: AudioPreparado, opciones: OpcionesTranscripcion) -> Transcripcion:
        datos = self._enviar(audio, opciones)
        metadatos = datos.get("metadata") or {}
        if audio.hablante is None and not metadatos.get("diarize_info"):
            # Deepgram informa `diarize_info` solo si su diarizador corrió.
            registro.warning("Deepgram no corrió el diarizador (request_id %s).", metadatos.get("request_id"))
        duracion = _numero(metadatos.get("duration"))
        duracion = duracion if duracion is not None else audio.duracion_s
        return Transcripcion(
            proveedor=self.nombre,
            modelo=self._modelo,
            idioma=opciones.idioma,
            segmentos=self._segmentos(datos, audio),
            duracion_audio=duracion,
            costo_estimado=self.costo_estimado(duracion),
        )

    def _segmentos(self, datos: dict, audio: AudioPreparado) -> list[Segmento]:
        hablante = audio.hablante or "desconocido"
        resultados = datos.get("results") or {}
        if audio.hablante is None:
            por_palabra = _segmentos_por_palabra(resultados)
            if por_palabra:
                return por_palabra
        frases = resultados.get("utterances") or []
        segmentos = []
        for frase in frases:
            texto = (frase.get("transcript") or "").strip()
            if not texto:
                continue
            segmentos.append(
                Segmento(
                    hablante=hablante,
                    etiqueta=_etiqueta(frase.get("speaker")) if audio.hablante is None else None,
                    inicio=_numero(frase.get("start")),
                    fin=_numero(frase.get("end")),
                    texto=texto,
                )
            )
        if segmentos or frases:
            return segmentos
        # Sin frases (no debería pasar con utterances=true): el texto entero.
        canales = resultados.get("channels") or [{}]
        alternativas = canales[0].get("alternatives") or [{}]
        texto = (alternativas[0].get("transcript") or "").strip()
        return [Segmento(hablante=hablante, inicio=None, fin=None, texto=texto)] if texto else []
