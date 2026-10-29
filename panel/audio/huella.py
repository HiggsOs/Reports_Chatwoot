"""Muestra la huella del servidor SFTP: `python -m panel.audio.huella HOST PUERTO`.

Se corre una vez al configurar, y el valor va a SFTP_HUELLA_HOST. Conviene
compararla con la que muestre el proveedor del hosting.
"""

import sys

from panel.audio.almacen import obtener_huella


def main(argumentos: list[str]) -> int:
    if len(argumentos) != 2 or not argumentos[1].isdigit():
        print("Uso: python -m panel.audio.huella HOST PUERTO", file=sys.stderr)
        return 2
    print(obtener_huella(argumentos[0], int(argumentos[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
