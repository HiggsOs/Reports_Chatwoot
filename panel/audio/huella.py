"""Muestra la huella del servidor SFTP: `python -m panel.audio.huella HOST PUERTO`.

Se corre una vez al configurar, y el valor va a SFTP_HUELLA_HOST. Conviene
compararla con la que muestre el proveedor del hosting.
"""

import socket
import sys

import paramiko

from panel.audio.almacen import TIEMPO_LIMITE_SEGUNDOS, obtener_huella


def main(argumentos: list[str]) -> int:
    if len(argumentos) != 2 or not argumentos[1].isdigit():
        print("Uso: python -m panel.audio.huella HOST PUERTO", file=sys.stderr)
        return 2
    host, puerto = argumentos[0], int(argumentos[1])
    try:
        print(obtener_huella(host, puerto))
    except socket.gaierror:
        print(f"No existe el nombre {host!r}: revise que esté bien escrito y que tenga DNS.", file=sys.stderr)
        return 1
    except TimeoutError:
        print(
            f"{host}:{puerto} no respondió en {TIEMPO_LIMITE_SEGUNDOS} s: lo más probable es que un "
            "firewall bloquee ese puerto o que SFTP no esté activado.",
            file=sys.stderr,
        )
        return 1
    except (OSError, paramiko.SSHException) as error:
        print(f"No se pudo conectar con {host}:{puerto}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
