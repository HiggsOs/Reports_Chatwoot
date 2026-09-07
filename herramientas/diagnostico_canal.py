"""Diagnóstico: qué información de canal trae tu Chatwoot.

Muestra los inboxes de la cuenta y qué campos de canal vienen en las
conversaciones, para decidir cómo se llena la columna nueva del reporte.

Uso:
    .venv/bin/python diagnostico_canal.py

Lee las credenciales del .env. Solo hace lecturas.
"""

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

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
BASE = env["CHATWOOT_BASE_URL"].rstrip("/")
CUENTA = int(env["CHATWOOT_ACCOUNT_ID"])
TOKEN = env["CHATWOOT_API_TOKEN"]

cliente = ClienteChatwoot(BASE, CUENTA, TOKEN)

print("=" * 68)
print("\n1. INBOXES DE LA CUENTA")
print("   (cada inbox es un canal configurado: un número de WhatsApp,")
print("    el widget de la web, una página de Facebook…)\n")

r = requests.get(
    f"{BASE}/api/v1/accounts/{CUENTA}/inboxes",
    headers={"api_access_token": TOKEN},
    timeout=30,
)
if r.status_code >= 400:
    print(f"   ERROR HTTP {r.status_code}: {r.text[:200]}")
    inboxes = {}
else:
    datos = r.json().get("payload") or []
    inboxes = {i["id"]: i for i in datos}
    for i in datos:
        print(f"   id={i['id']:<4} nombre={i.get('name','?'):<28} tipo={i.get('channel_type','?')}")
    if not datos:
        print("   (ninguno)")

print("\n" + "=" * 68)
print("\n2. QUÉ TRAE UNA CONVERSACIÓN\n")

hasta = datetime.now(BOGOTA)
desde = hasta - timedelta(days=3)
conversaciones = cliente.listar_conversaciones(desde, hasta)
print(f"   Analizando {len(conversaciones)} conversaciones de los últimos 3 días.\n")

if not conversaciones:
    raise SystemExit("   No hay conversaciones en el rango; probá un rango más amplio.")

muestra = conversaciones[0]
print("   Campos de la primera conversación relacionados con el canal:")
for clave in ("inbox_id", "channel", "additional_attributes"):
    if clave in muestra:
        print(f"     {clave}: {json.dumps(muestra[clave], ensure_ascii=False)[:120]}")
meta = muestra.get("meta") or {}
for clave in ("channel", "sender"):
    if clave in meta:
        valor = json.dumps(meta[clave], ensure_ascii=False)
        print(f"     meta.{clave}: {valor[:120]}")

print("\n   Todas las claves disponibles en una conversación:")
print(f"     {sorted(muestra.keys())}")
print("   Claves dentro de meta:")
print(f"     {sorted(meta.keys())}")

print("\n" + "=" * 68)
print("\n3. DISTRIBUCIÓN REAL POR CANAL\n")

por_inbox = Counter(c.get("inbox_id") for c in conversaciones)
por_channel = Counter((c.get("meta") or {}).get("channel") for c in conversaciones)

print("   Por inbox_id (con el nombre del inbox):")
for inbox_id, cuantas in por_inbox.most_common():
    info = inboxes.get(inbox_id, {})
    nombre = info.get("name", "¿desconocido?")
    tipo = info.get("channel_type", "?")
    print(f"     {cuantas:>4}  id={inbox_id}  {nombre}  ({tipo})")

print("\n   Por meta.channel:")
for canal, cuantas in por_channel.most_common():
    print(f"     {cuantas:>4}  {canal}")

sin_inbox = sum(1 for c in conversaciones if not c.get("inbox_id"))
if sin_inbox:
    print(f"\n   ⚠ {sin_inbox} conversaciones sin inbox_id")

print("\n" + "=" * 68)
print("\nPásame esta salida y defino cómo se llena la columna 'canal'.")
