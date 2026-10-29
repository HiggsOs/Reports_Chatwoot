"""Un servidor SFTP mínimo con paramiko, sobre una carpeta, para las pruebas.

Adaptado del servidor de prueba de paramiko. Solo acepta el usuario y la clave
de abajo, y escucha en 127.0.0.1 en un puerto libre.
"""

import os
import socket
import threading
from pathlib import Path

import paramiko
from paramiko.sftp import SFTP_OK

USUARIO = "audios"
CLAVE = "clave-secreta"


class _Autenticacion(paramiko.ServerInterface):
    def check_auth_password(self, usuario, clave):
        if (usuario, clave) == (USUARIO, CLAVE):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, usuario):
        return "password"

    def check_channel_request(self, tipo, canal_id):
        if tipo == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _Archivo(paramiko.SFTPHandle):
    def stat(self):
        return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))

    def chattr(self, atributos):
        return SFTP_OK


def _sftp_sobre(raiz: Path):
    class _SFTP(paramiko.SFTPServerInterface):
        def _real(self, ruta):
            return str(raiz) + self.canonicalize(ruta)

        def _error(self, error):
            return paramiko.SFTPServer.convert_errno(error.errno)

        def stat(self, ruta):
            try:
                return paramiko.SFTPAttributes.from_stat(os.stat(self._real(ruta)))
            except OSError as error:
                return self._error(error)

        lstat = stat

        def list_folder(self, ruta):
            try:
                real = self._real(ruta)
                return [
                    paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(real, n)), n)
                    for n in os.listdir(real)
                ]
            except OSError as error:
                return self._error(error)

        def open(self, ruta, flags, atributos):
            real = self._real(ruta)
            try:
                descriptor = os.open(real, flags, 0o644)
            except OSError as error:
                return self._error(error)
            modo = "wb" if flags & os.O_WRONLY else "r+b" if flags & os.O_RDWR else "rb"
            archivo = os.fdopen(descriptor, modo)
            manejador = _Archivo(flags)
            manejador.filename = real
            manejador.readfile = archivo
            manejador.writefile = archivo
            return manejador

        def remove(self, ruta):
            try:
                os.remove(self._real(ruta))
            except OSError as error:
                return self._error(error)
            return SFTP_OK

        def rename(self, vieja, nueva):
            if os.path.exists(self._real(nueva)):
                return paramiko.sftp.SFTP_FAILURE
            os.rename(self._real(vieja), self._real(nueva))
            return SFTP_OK

        def posix_rename(self, vieja, nueva):
            os.replace(self._real(vieja), self._real(nueva))
            return SFTP_OK

        def mkdir(self, ruta, atributos):
            try:
                os.mkdir(self._real(ruta))
            except OSError as error:
                return self._error(error)
            return SFTP_OK

    return _SFTP


class ServidorSFTP:
    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        self.clave_servidor = paramiko.RSAKey.generate(2048)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(10)
        self.puerto = self._socket.getsockname()[1]
        self._transportes: list[paramiko.Transport] = []
        self._hilo = threading.Thread(target=self._atender, daemon=True)
        self._hilo.start()

    def _atender(self) -> None:
        while True:
            try:
                conexion, _ = self._socket.accept()
            except OSError:
                return
            # Cada conexión en su hilo: una que el cliente corta a mitad de la
            # negociación no debe trabar a las siguientes.
            threading.Thread(target=self._negociar, args=(conexion,), daemon=True).start()

    def _negociar(self, conexion) -> None:
        transporte = paramiko.Transport(conexion)
        transporte.add_server_key(self.clave_servidor)
        transporte.set_subsystem_handler("sftp", paramiko.SFTPServer, _sftp_sobre(self.raiz))
        try:
            transporte.start_server(server=_Autenticacion())
        except (paramiko.SSHException, EOFError, OSError):
            return
        # No se llama a accept(): el canal que devuelve se cerraría al perder la
        # referencia, y el subsistema SFTP no lo necesita.
        self._transportes.append(transporte)

    def cerrar(self) -> None:
        self._socket.close()
        for transporte in self._transportes:
            transporte.close()
