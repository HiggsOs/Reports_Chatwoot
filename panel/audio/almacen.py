"""Dónde quedan guardados los MP3 (patrón Adapter: puertos y adaptadores).

El resto del sistema solo conoce `AlmacenAudio` y guarda rutas relativas
(`cloudtalk/2026/10/123.mp3`). Cambiar de servidor, o pasar a S3, es escribir
otra implementación y cambiar ALMACEN_TIPO.
"""

import base64
import hashlib
import posixpath
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Protocol

import paramiko

TIEMPO_LIMITE_SEGUNDOS = 30


class AlmacenError(Exception):
    """No se pudo leer o escribir en el almacén."""


class AlmacenAudio(Protocol):
    def subir(self, ruta: str, contenido: bytes) -> None: ...

    def bajar(self, ruta: str) -> bytes: ...

    def existe(self, ruta: str) -> bool: ...

    def borrar(self, ruta: str) -> None:
        """No falla si el archivo ya no existe."""
        ...


def validar_ruta(ruta: str) -> PurePosixPath:
    """Solo rutas relativas y sin «..»: nunca se escribe fuera del directorio."""
    relativa = PurePosixPath(ruta)
    if not ruta or relativa.is_absolute() or ".." in relativa.parts:
        raise AlmacenError(f"Ruta de audio no válida: {ruta!r}")
    return relativa


class AlmacenLocal:
    """Una carpeta en disco. Para desarrollo y pruebas: en EasyPanel la app y
    la sincronización no comparten disco."""

    def __init__(self, directorio: Path) -> None:
        self._directorio = Path(directorio)

    def _ruta(self, ruta: str) -> Path:
        return self._directorio / validar_ruta(ruta)

    def subir(self, ruta: str, contenido: bytes) -> None:
        destino = self._ruta(ruta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".parcial")
        parcial.write_bytes(contenido)
        parcial.replace(destino)

    def bajar(self, ruta: str) -> bytes:
        try:
            return self._ruta(ruta).read_bytes()
        except OSError as error:
            raise AlmacenError(f"No se pudo leer {ruta}: {error}") from error

    def existe(self, ruta: str) -> bool:
        return self._ruta(ruta).is_file()

    def borrar(self, ruta: str) -> None:
        self._ruta(ruta).unlink(missing_ok=True)


def huella_sha256(clave: paramiko.PKey) -> str:
    """La huella con el formato de OpenSSH: «SHA256:» y el hash en base64."""
    resumen = hashlib.sha256(clave.asbytes()).digest()
    return "SHA256:" + base64.b64encode(resumen).decode().rstrip("=")


def _normalizar_huella(huella: str) -> str:
    huella = huella.strip()
    return huella if huella.startswith("SHA256:") else f"SHA256:{huella}"


class AlmacenSFTP:
    """El SFTP del hosting (en Plesk: «Permitir SFTP para cuentas FTP»).

    Se verifica la huella del servidor en cada conexión: sin eso, alguien que
    se hiciera pasar por el servidor recibiría las grabaciones.
    """

    def __init__(
        self,
        host: str,
        puerto: int,
        usuario: str,
        clave: str,
        directorio: str,
        huella: str,
    ) -> None:
        self._host = host
        self._puerto = puerto
        self._usuario = usuario
        self._clave = clave
        self._directorio = directorio.rstrip("/") or "."
        self._huella = _normalizar_huella(huella)

    @contextmanager
    def _conexion(self) -> Iterator[paramiko.SFTPClient]:
        try:
            transporte = paramiko.Transport((self._host, self._puerto))
            transporte.banner_timeout = TIEMPO_LIMITE_SEGUNDOS
        except (OSError, paramiko.SSHException) as error:
            raise AlmacenError(f"No se pudo conectar con {self._host}:{self._puerto}: {error}") from error
        try:
            try:
                transporte.start_client(timeout=TIEMPO_LIMITE_SEGUNDOS)
                recibida = huella_sha256(transporte.get_remote_server_key())
                if recibida != self._huella:
                    raise AlmacenError(
                        f"La huella del servidor SFTP es {recibida} y se esperaba "
                        f"{self._huella}. No se envía nada: revise SFTP_HUELLA_HOST."
                    )
                transporte.auth_password(self._usuario, self._clave)
                cliente = paramiko.SFTPClient.from_transport(transporte)
            except (OSError, paramiko.SSHException) as error:
                raise AlmacenError(f"Falló la conexión SFTP con {self._host}: {error}") from error
            cliente.get_channel().settimeout(TIEMPO_LIMITE_SEGUNDOS)
            yield cliente
        finally:
            transporte.close()

    def _ruta(self, ruta: str) -> str:
        return posixpath.join(self._directorio, str(validar_ruta(ruta)))

    @staticmethod
    def _crear_directorios(cliente: paramiko.SFTPClient, directorio: str) -> None:
        actual = ""
        for parte in directorio.split("/"):
            actual = f"{actual}/{parte}" if actual or directorio.startswith("/") else parte
            if not parte or parte == ".":
                continue
            try:
                cliente.stat(actual)
            except FileNotFoundError:
                cliente.mkdir(actual)

    def subir(self, ruta: str, contenido: bytes) -> None:
        destino = self._ruta(ruta)
        parcial = destino + ".parcial"
        with self._conexion() as cliente:
            try:
                self._crear_directorios(cliente, posixpath.dirname(destino))
                with cliente.open(parcial, "wb") as archivo:
                    archivo.write(contenido)
                try:
                    cliente.posix_rename(parcial, destino)
                except OSError:
                    # Servidor sin la extensión posix-rename: se borra y se renombra.
                    try:
                        cliente.remove(destino)
                    except FileNotFoundError:
                        pass
                    cliente.rename(parcial, destino)
            except OSError as error:
                raise AlmacenError(f"No se pudo subir {ruta}: {error}") from error

    def bajar(self, ruta: str) -> bytes:
        with self._conexion() as cliente:
            try:
                with cliente.open(self._ruta(ruta), "rb") as archivo:
                    return archivo.read()
            except OSError as error:
                raise AlmacenError(f"No se pudo leer {ruta}: {error}") from error

    def existe(self, ruta: str) -> bool:
        with self._conexion() as cliente:
            try:
                cliente.stat(self._ruta(ruta))
            except FileNotFoundError:
                return False
            return True

    def borrar(self, ruta: str) -> None:
        with self._conexion() as cliente:
            try:
                cliente.remove(self._ruta(ruta))
            except FileNotFoundError:
                pass
            except OSError as error:
                raise AlmacenError(f"No se pudo borrar {ruta}: {error}") from error


def obtener_huella(host: str, puerto: int) -> str:
    """La huella que presenta el servidor, para cargarla en SFTP_HUELLA_HOST."""
    transporte = paramiko.Transport((host, puerto))
    try:
        transporte.start_client(timeout=TIEMPO_LIMITE_SEGUNDOS)
        return huella_sha256(transporte.get_remote_server_key())
    finally:
        transporte.close()
