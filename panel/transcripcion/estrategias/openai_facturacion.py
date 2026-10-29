"""Lo cobrado por OpenAI: las APIs de uso y de costos de la organización.

- `GET /organization/usage/audio_transcriptions`, agrupado por modelo: los
  segundos de audio transcritos.
- `GET /organization/costs`, agrupado por concepto (`line_item`): los USD
  cobrados. El concepto trae el nombre del modelo; puede haber más de uno por
  modelo (por ejemplo, entrada y salida), y se suman.

Las dos piden una clave de administrador (OPENAI_ADMIN_KEY), distinta de la
que transcribe. OPENAI_PROJECT_ID limita la lectura a un proyecto, para no
mezclar lo que gastan otras aplicaciones de la misma organización.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests

from panel.transcripcion.estrategias.openai import MODELOS, URL_POR_DEFECTO
from panel.transcripcion.facturacion import (
    CobroModelo,
    FacturacionError,
    FacturacionNoDisponible,
    registrar,
)

TIEMPO_LIMITE_SEGUNDOS = 60
# Los máximos de cada API para baldes de un día.
DIAS_POR_PAGINA_USO = 31
DIAS_POR_PAGINA_COSTOS = 180
PAGINAS_MAXIMAS = 50


def _decimal(valor) -> Decimal | None:
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None


@registrar
class FacturacionOpenAI:
    proveedor = "openai"

    def __init__(
        self,
        clave_admin: str,
        proyecto: str | None = None,
        url: str = URL_POR_DEFECTO,
        sesion: requests.Session | None = None,
    ) -> None:
        self._clave = clave_admin
        self._proyecto = proyecto
        self._url = url.rstrip("/")
        self._sesion = sesion or requests.Session()

    @classmethod
    def desde_config(cls, valores: Mapping[str, str]) -> "FacturacionOpenAI":
        clave = (valores.get("OPENAI_ADMIN_KEY") or "").strip()
        if not clave:
            raise FacturacionNoDisponible("Falta OPENAI_ADMIN_KEY.")
        return cls(
            clave_admin=clave,
            proyecto=(valores.get("OPENAI_PROJECT_ID") or "").strip() or None,
            url=(valores.get("OPENAI_BASE_URL") or URL_POR_DEFECTO).strip(),
        )

    def _baldes(self, ruta: str, params: dict) -> list[dict]:
        """Todos los baldes del período, siguiendo las páginas."""
        if self._proyecto:
            params = {**params, "project_ids": [self._proyecto]}
        baldes, pagina = [], None
        for _ in range(PAGINAS_MAXIMAS):
            pedido = {**params, **({"page": pagina} if pagina else {})}
            try:
                respuesta = self._sesion.get(
                    f"{self._url}{ruta}",
                    headers={"Authorization": f"Bearer {self._clave}"},
                    params=pedido,
                    timeout=TIEMPO_LIMITE_SEGUNDOS,
                )
            except requests.RequestException as error:
                raise FacturacionError(f"OpenAI no respondió: {error}") from error
            if respuesta.status_code in (401, 403):
                raise FacturacionError(
                    "OpenAI rechazó la clave de administrador. Revise OPENAI_ADMIN_KEY: "
                    "tiene que ser una Admin key (sk-admin-…), no la clave que transcribe."
                )
            if respuesta.status_code >= 400:
                raise FacturacionError(
                    f"OpenAI respondió {respuesta.status_code}: {respuesta.text[:300]}"
                )
            datos = respuesta.json()
            baldes += datos.get("data") or []
            pagina = datos.get("next_page")
            if not datos.get("has_more") or not pagina:
                return baldes
        raise FacturacionError("OpenAI devolvió demasiadas páginas; elija un período más corto.")

    def _segundos_por_modelo(self, desde: datetime, hasta: datetime) -> dict[str, float]:
        segundos: dict[str, float] = {}
        baldes = self._baldes(
            "/organization/usage/audio_transcriptions",
            {
                "start_time": int(desde.timestamp()),
                "end_time": int(hasta.timestamp()),
                "bucket_width": "1d",
                "group_by": ["model"],
                "limit": DIAS_POR_PAGINA_USO,
            },
        )
        for balde in baldes:
            for resultado in balde.get("results") or []:
                modelo = resultado.get("model")
                if modelo:
                    segundos[modelo] = segundos.get(modelo, 0.0) + float(resultado.get("seconds") or 0)
        return segundos

    def _costos_por_concepto(self, desde: datetime, hasta: datetime) -> dict[str, Decimal]:
        costos: dict[str, Decimal] = {}
        baldes = self._baldes(
            "/organization/costs",
            {
                "start_time": int(desde.timestamp()),
                "end_time": int(hasta.timestamp()),
                "bucket_width": "1d",
                "group_by": ["line_item"],
                "limit": DIAS_POR_PAGINA_COSTOS,
            },
        )
        for balde in baldes:
            for resultado in balde.get("results") or []:
                monto = resultado.get("amount") or {}
                valor = _decimal(monto.get("value"))
                concepto = (resultado.get("line_item") or "").strip()
                if valor is None or not concepto:
                    continue
                if (monto.get("currency") or "usd").lower() != "usd":
                    raise FacturacionError(f"OpenAI cobra en {monto['currency']}; el panel usa USD.")
                costos[concepto] = costos.get(concepto, Decimal("0")) + valor
        return costos

    def cobrado(self, desde: datetime, hasta: datetime) -> list[CobroModelo]:
        segundos = self._segundos_por_modelo(desde, hasta)
        costos = self._costos_por_concepto(desde, hasta)
        # El más largo primero: «gpt-4o-transcribe-diarize» antes que
        # «gpt-4o-transcribe», que está contenido en él.
        conocidos = sorted({*MODELOS, *segundos}, key=len, reverse=True)
        por_modelo: dict[str, Decimal] = {}
        for concepto, valor in costos.items():
            texto = concepto.lower()
            modelo = next((m for m in conocidos if m.lower() in texto), None)
            if modelo is not None:  # lo que no es transcripción no se cuenta
                por_modelo[modelo] = por_modelo.get(modelo, Decimal("0")) + valor
        return [
            CobroModelo(modelo=modelo, segundos=segundos.get(modelo, 0.0), costo=por_modelo.get(modelo))
            for modelo in sorted({*segundos, *por_modelo})
        ]
