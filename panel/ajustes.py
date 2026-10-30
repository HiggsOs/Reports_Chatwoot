"""Ajustes que se cargan desde el panel en lugar de variables de entorno.

Cada ajuste tiene el mismo nombre que su variable de entorno
(`CHATWOOT_API_TOKEN`, `FTP_PASSWORD`…). Al arrancar, el panel y la
sincronización leen el entorno y le superponen lo guardado aquí: un valor del
panel pisa al del entorno, y borrarlo del panel vuelve al del entorno.

Lo que sigue siendo solo de entorno (porque hace falta antes de poder leer la
base o porque es la llave de todo): DATABASE_URL, el usuario y la contraseña del
panel, APP_COOKIE_KEY y la llave de cifrado.

Las claves y contraseñas se guardan cifradas con Fernet. La llave sale de
PANEL_CLAVE_CIFRADO o, si no está, de APP_COOKIE_KEY: si cambia, las claves
guardadas dejan de poder leerse y hay que cargarlas de nuevo.
"""

import base64
import hashlib
import logging
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from panel.db.base import unidad_de_trabajo
from panel.db.modelos import Ajuste

registro = logging.getLogger(__name__)


class Campo(BaseModel):
    model_config = ConfigDict(frozen=True)

    clave: str
    secreto: bool = False


def _campos(*nombres: str, secretos: tuple[str, ...] = ()) -> dict[str, Campo]:
    return {n: Campo(clave=n, secreto=n in secretos) for n in nombres}


# Lo único que se puede guardar. Una clave que no está aquí no se acepta: así un
# error de tipeo no queda guardado sin efecto.
CAMPOS: dict[str, Campo] = _campos(
    # Chatwoot
    "CHATWOOT_BASE_URL",
    "CHATWOOT_ACCOUNT_ID",
    "CHATWOOT_API_TOKEN",
    "CHATWOOT_DIAS_RELECTURA",
    # CloudTalk
    "CLOUDTALK_API_KEY_ID",
    "CLOUDTALK_API_KEY_SECRET",
    "CLOUDTALK_CANAL_AGENTE",
    # Sincronización
    "SYNC_INTERVALO_MINUTOS",
    "SYNC_DIAS_INICIALES",
    # Almacén de audio
    "ALMACEN_TIPO",
    "FTP_HOST",
    "FTP_PORT",
    "FTP_USER",
    "FTP_PASSWORD",
    "FTP_DIR",
    "SFTP_HUELLA_HOST",
    "AUDIO_RETENCION_DIAS",
    # Transcripción
    "TRANSCRIPCION_PROVEEDOR",
    "TRANSCRIPCION_RESPALDO",
    "TRANSCRIPCION_IDIOMA",
    "TRANSCRIPCION_VOCABULARIO",
    "TRANSCRIPCION_MODELOS",
    "TRANSCRIPCION_TOPE_MENSUAL_USD",
    "TRANSCRIPCION_AVISO_PORCENTAJE",
    "TRANSCRIPCION_CONFIRMAR_LOTE_USD",
    "TRANSCRIPCION_AUTO_MIN_SEGUNDOS",
    "OPENAI_API_KEY",
    secretos=("CHATWOOT_API_TOKEN", "CLOUDTALK_API_KEY_SECRET", "FTP_PASSWORD", "OPENAI_API_KEY"),
)


class AjusteDesconocido(ValueError):
    """Se intentó guardar un ajuste que no existe."""


class Cifrador:
    def __init__(self, llave: str) -> None:
        if not llave.strip():
            raise ValueError("Hace falta una llave para cifrar los ajustes.")
        # Fernet pide 32 bytes en base64; se derivan de la llave, sea cual sea.
        resumen = hashlib.sha256(("panel-ajustes:" + llave).encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(resumen))

    @classmethod
    def desde_entorno(cls, entorno: Mapping[str, str]) -> "Cifrador":
        return cls((entorno.get("PANEL_CLAVE_CIFRADO") or "").strip() or entorno.get("APP_COOKIE_KEY", ""))

    def cifrar(self, texto: str) -> str:
        return self._fernet.encrypt(texto.encode()).decode()

    def descifrar(self, texto: str) -> str:
        return self._fernet.decrypt(texto.encode()).decode()


class LecturaAjustes(BaseModel):
    valores: dict[str, str]
    # Secretos guardados con otra llave: no se pueden usar y hay que cargarlos de nuevo.
    ilegibles: list[str] = []


def enmascarar(valor: str) -> str:
    """Lo que se muestra de una clave guardada: solo sus últimos 4 caracteres."""
    if not valor:
        return ""
    return "•" * 12 + valor[-4:] if len(valor) > 8 else "•" * 8


class RepositorioAjustes:
    def __init__(self, sesion: Session, cifrador: Cifrador) -> None:
        self._sesion = sesion
        self._cifrador = cifrador

    def leer(self) -> LecturaAjustes:
        valores, ilegibles = {}, []
        for fila in self._sesion.scalars(select(Ajuste)):
            if fila.clave not in CAMPOS:
                continue
            if not fila.secreto:
                valores[fila.clave] = fila.valor
                continue
            try:
                valores[fila.clave] = self._cifrador.descifrar(fila.valor)
            except InvalidToken:
                registro.warning("No se pudo descifrar el ajuste %s: cambió la llave.", fila.clave)
                ilegibles.append(fila.clave)
        return LecturaAjustes(valores=valores, ilegibles=sorted(ilegibles))

    def guardar(self, cambios: Mapping[str, str | None]) -> None:
        """`None` o texto vacío borra el ajuste: vuelve a valer el entorno."""
        desconocidas = [clave for clave in cambios if clave not in CAMPOS]
        if desconocidas:
            raise AjusteDesconocido("Ajustes que no existen: " + ", ".join(sorted(desconocidas)))
        for clave, valor in cambios.items():
            fila = self._sesion.get(Ajuste, clave)
            if valor is None or valor == "":
                if fila is not None:
                    self._sesion.delete(fila)
                continue
            secreto = CAMPOS[clave].secreto
            guardado = self._cifrador.cifrar(valor) if secreto else valor
            if fila is None:
                self._sesion.add(Ajuste(clave=clave, valor=guardado, secreto=secreto))
            else:
                fila.valor, fila.secreto = guardado, secreto


def entorno_efectivo(
    entorno: Mapping[str, str], fabrica: sessionmaker[Session]
) -> tuple[dict[str, str], LecturaAjustes]:
    """El entorno con los ajustes del panel encima."""
    with unidad_de_trabajo(fabrica) as sesion:
        lectura = RepositorioAjustes(sesion, Cifrador.desde_entorno(entorno)).leer()
    return {**entorno, **lectura.valores}, lectura


def origenes(entorno: Mapping[str, str], lectura: LecturaAjustes) -> dict[str, str]:
    """De dónde sale cada ajuste: «panel», «entorno» o nada si no está."""
    resultado = {}
    for clave in CAMPOS:
        if clave in lectura.valores:
            resultado[clave] = "panel"
        elif (entorno.get(clave) or "").strip():
            resultado[clave] = "entorno"
    return resultado
