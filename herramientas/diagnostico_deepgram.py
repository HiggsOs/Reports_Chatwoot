"""Diagnóstico: cuántas voces separa Deepgram en una grabación.

Manda el audio a Deepgram con los mismos parámetros que el panel
(diarize_model=latest, utterances, smart_format) y muestra:

1. Cómo es el audio: canales, frecuencia, duración.
2. Cuántas voces detecta Deepgram por palabra y por utterance.
3. Las primeras frases como las arma el panel (por palabra).
4. Si el audio es estéreo: qué pasa pidiéndolo por canal (multichannel).

Uso, desde la raíz del proyecto:
    .venv/bin/python herramientas/diagnostico_deepgram.py llamada.mp3 [--modelo nova-3] [--idioma es]

El audio se baja del panel: en la llamada, «Escuchar la llamada» y después el
botón de descarga (⤓) al lado de la velocidad. Lee DEEPGRAM_API_KEY del
.env o del entorno. Transcribe una vez (dos si es estéreo): cuesta lo mismo
que transcribir la llamada desde el panel.
"""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from panel.transcripcion.estrategias.deepgram import _segmentos_por_palabra  # noqa: E402

URL = "https://api.deepgram.com/v1/listen"


def clave() -> str:
    if os.environ.get("DEEPGRAM_API_KEY"):
        return os.environ["DEEPGRAM_API_KEY"].strip()
    env = Path(".env")
    if env.exists():
        for linea in env.read_text(encoding="utf-8").splitlines():
            nombre, _, valor = linea.partition("=")
            if nombre.strip() == "DEEPGRAM_API_KEY" and valor.strip():
                return valor.strip().strip("\"'")
    raise SystemExit("Falta DEEPGRAM_API_KEY en el .env o en el entorno.")


def info_audio(ruta: Path) -> dict:
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_name,channels,sample_rate,bit_rate:format=duration", "-of", "json", str(ruta)],
        capture_output=True, check=True,
    ).stdout
    datos = json.loads(salida)
    return {**(datos.get("streams") or [{}])[0], **(datos.get("format") or {})}


def pedir(contenido: bytes, tipo: str, modelo: str, idioma: str, multicanal: bool, diarizador: str = "latest") -> dict:
    parametros = [("model", modelo), ("language", idioma), ("punctuate", "true"), ("smart_format", "true"),
                  ("utterances", "true")]
    if multicanal:
        parametros.append(("multichannel", "true"))
    elif diarizador == "viejo":
        parametros.append(("diarize", "true"))  # el parámetro obsoleto, para comparar
    else:
        parametros.append(("diarize_model", diarizador))
    respuesta = requests.post(URL, params=parametros, data=contenido, timeout=600,
                              headers={"Authorization": f"Token {clave()}", "Content-Type": tipo})
    if respuesta.status_code >= 400:
        raise SystemExit(f"Deepgram respondió {respuesta.status_code}: {respuesta.text[:500]}")
    return respuesta.json()


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("audio", type=Path)
    argumentos.add_argument("--modelo", default="nova-3")
    argumentos.add_argument("--idioma", default="es")
    argumentos.add_argument("--diarizador", default="latest",
                            help="latest (el del panel), v1, v2, o «viejo» para el diarize=true obsoleto")
    opciones = argumentos.parse_args()
    ruta = opciones.audio
    tipo = "audio/wav" if ruta.suffix.lower() == ".wav" else "audio/mpeg"

    print("=" * 68, "\n1. EL AUDIO\n")
    info = info_audio(ruta)
    print(f"   Formato: {info.get('codec_name')} · {info.get('channels')} canal(es) · "
          f"{info.get('sample_rate')} Hz · {info.get('bit_rate') or '?'} bit/s · {float(info.get('duration') or 0):.0f} s")

    print("\n" + "=" * 68, f"\n2. VOCES QUE DETECTA DEEPGRAM ({opciones.modelo}, {opciones.idioma})\n")
    datos = pedir(ruta.read_bytes(), tipo, opciones.modelo, opciones.idioma, multicanal=False,
                  diarizador=opciones.diarizador)
    resultados = datos.get("results") or {}
    metadatos = datos.get("metadata") or {}
    print(f"   Diarizador: {opciones.diarizador} · diarize_info: {metadatos.get('diarize_info') or 'NO VINO (no corrió)'}")
    palabras = [p for u in resultados.get("utterances") or [] for p in u.get("words") or []] or (
        ((resultados.get("channels") or [{}])[0].get("alternatives") or [{}])[0].get("words") or [])
    por_palabra = Counter(p.get("speaker") for p in palabras)
    por_utterance = Counter(u.get("speaker") for u in resultados.get("utterances") or [])
    print(f"   Por palabra:   {dict(por_palabra)}  ({len(palabras)} palabras)")
    print(f"   Por utterance: {dict(por_utterance)}  ({sum(por_utterance.values())} utterances)")
    if len([v for v in por_palabra if v is not None]) <= 1:
        print("\n   → Deepgram oyó una sola voz en toda la grabación. No es cómo la lee el panel:")
        print("     la diarización no separó estas voces (audio de una sola persona, muy")
        print("     comprimido, o voces muy parecidas). Pruebe el WAV original de CloudTalk.")
    elif len([v for v in por_utterance if v is not None]) <= 1:
        print("\n   → Las palabras tienen varias voces pero las utterances una sola: el panel")
        print("     ahora arma las frases por palabra, así que sí las separa.")

    print("\n" + "=" * 68, "\n3. PRIMERAS FRASES, COMO LAS ARMA EL PANEL\n")
    for segmento in _segmentos_por_palabra(resultados)[:15]:
        print(f"   [{segmento.inicio or 0:6.1f}s] Hablante {segmento.etiqueta}: {segmento.texto}")

    if int(info.get("channels") or 1) >= 2:
        print("\n" + "=" * 68, "\n4. ESTÉREO: CADA CANAL POR SEPARADO (multichannel)\n")
        canales = (pedir(ruta.read_bytes(), tipo, opciones.modelo, opciones.idioma, multicanal=True)
                   .get("results") or {}).get("channels") or []
        for numero, canal in enumerate(canales):
            texto = ((canal.get("alternatives") or [{}])[0].get("transcript") or "").strip()
            print(f"   Canal {numero}: {texto[:200]}{'…' if len(texto) > 200 else ''}")
        print("\n   → Si cada canal tiene a una sola persona, la grabación es estéreo real y el")
        print("     panel la transcribe por canal (Agente/Cliente sin diarización).")


if __name__ == "__main__":
    main()
