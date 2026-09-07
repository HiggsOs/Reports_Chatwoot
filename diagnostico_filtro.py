"""Diagnóstico 3: comprueba el cliente ya corregido contra tu instancia.

A diferencia de las rondas anteriores, este script usa `ClienteChatwoot` tal
como lo usa la app, así que lo que verifica es el código real.

Uso:
    .venv/bin/python diagnostico_filtro.py

Lee las credenciales del .env. Solo hace lecturas.
"""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from chatwoot import ClienteChatwoot

BOGOTA = ZoneInfo("America/Bogota")


def cargar_env(ruta=Path(".env")):
    if not ruta.exists():
        raise SystemExit("No encontré .env en este directorio.")
    valores = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valores[clave.strip()] = valor.strip().strip("\"'")
    return valores


env = cargar_env()
cliente = ClienteChatwoot(
    env["CHATWOOT_BASE_URL"].rstrip("/"),
    int(env["CHATWOOT_ACCOUNT_ID"]),
    env["CHATWOOT_API_TOKEN"],
)


def dia(fecha):
    inicio = fecha.replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio, inicio.replace(hour=23, minute=59, second=59)


def resumen(titulo, desde, hasta):
    print(f"\n{titulo}")
    print(f"  Rango pedido: {desde:%Y-%m-%d %H:%M} a {hasta:%Y-%m-%d %H:%M}")
    conversaciones = cliente.listar_conversaciones(desde, hasta)
    print(f"  Total: {len(conversaciones)} conversaciones")

    if not conversaciones:
        return conversaciones

    fechas = [
        datetime.fromtimestamp(float(c["created_at"]), BOGOTA)
        for c in conversaciones
        if c.get("created_at")
    ]
    print(f"  Primera: {min(fechas):%Y-%m-%d %H:%M}   Última: {max(fechas):%Y-%m-%d %H:%M}")
    fuera = [f for f in fechas if not (desde <= f <= hasta)]
    if fuera:
        print(f"  ✗ {len(fuera)} fuera del rango — el recorte no está funcionando")
    else:
        print("  ✓ Todas dentro del rango")
    return conversaciones


print("Probando el cliente corregido contra tu instancia\n" + "=" * 60)

ahora = datetime.now(BOGOTA)

# 1. El caso que antes devolvía 0.
ayer_desde, ayer_hasta = dia(ahora - timedelta(days=1))
del_dia = resumen("1. UN SOLO DÍA (el que antes devolvía 0)", ayer_desde, ayer_hasta)
if del_dia:
    print("  ✓ ARREGLADO: un solo día ya devuelve conversaciones")
else:
    print("  ⚠ Sigue en 0. Puede ser real (día sin conversaciones) — probá otro día")
    print("    o comparalo contra la interfaz de Chatwoot antes de concluir.")

# 2. Coherencia: la suma de los días sueltos debe dar el total del rango.
print("\n2. COHERENCIA — la suma de días sueltos vs. el rango completo")
inicio_ventana = (ahora - timedelta(days=4)).replace(hour=0, minute=0, second=0, microsecond=0)
fin_ventana = (ahora - timedelta(days=1)).replace(hour=23, minute=59, second=59)

total_rango = len(cliente.listar_conversaciones(inicio_ventana, fin_ventana))
suma_dias = 0
for i in range(4):
    d_desde, d_hasta = dia(inicio_ventana + timedelta(days=i))
    n = len(cliente.listar_conversaciones(d_desde, d_hasta))
    print(f"     {d_desde:%Y-%m-%d}: {n}")
    suma_dias += n

print(f"  Rango completo de 4 días: {total_rango}")
print(f"  Suma de los 4 días sueltos: {suma_dias}")
if total_rango == suma_dias:
    print("  ✓ Coinciden — el filtro es coherente y no pierde ni duplica nada")
else:
    print(f"  ✗ No coinciden (diferencia de {abs(total_rango - suma_dias)})")
    print("    Algo se pierde o se duplica en los bordes de los días.")

# 3. Un día concreto para contrastar a mano.
print("\n3. PARA COMPARAR CONTRA CHATWOOT")
elegido_desde, elegido_hasta = dia(ahora - timedelta(days=2))
conversaciones = cliente.listar_conversaciones(elegido_desde, elegido_hasta)
print(f"  El {elegido_desde:%Y-%m-%d} hubo {len(conversaciones)} conversaciones.")
print("  Filtrá ese mismo día en la interfaz de Chatwoot: el número debe coincidir.")

print("\n" + "=" * 60)
