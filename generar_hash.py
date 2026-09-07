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
