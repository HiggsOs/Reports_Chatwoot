import shutil

import pytest

from panel.audio.conversion import a_mp3, analizar, canales_iguales
from panel.transcripcion.base import AudioPreparado
from panel.transcripcion.preparacion import (
    EstereoDuplicado,
    EstereoPorCanal,
    Mono,
    como_mono,
    elegir_preparador,
    partir,
    preparar,
)
from tests.audio_de_prueba import wav

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Falta ffmpeg.")


@pytest.fixture(scope="module")
def mono():
    return a_mp3(wav(segundos=4), canales=1)


@pytest.fixture(scope="module")
def estereo():
    return a_mp3(wav(segundos=4, canales=2), canales=2)


@pytest.fixture(scope="module")
def duplicado():
    return a_mp3(wav(segundos=4, canales=2, duplicado=True), canales=2)


def test_detecta_canales_iguales(estereo, duplicado):
    assert canales_iguales(duplicado)
    assert not canales_iguales(estereo)


def test_la_fabrica_elige_el_preparador(mono, estereo, duplicado):
    assert isinstance(elegir_preparador(mono, "izquierdo")[0], Mono)
    assert isinstance(elegir_preparador(duplicado, "izquierdo")[0], EstereoDuplicado)
    assert isinstance(elegir_preparador(estereo, "izquierdo")[0], EstereoPorCanal)
    assert elegir_preparador(mono, "izquierdo")[1] == pytest.approx(4.0, abs=0.2)


def test_mono_se_transcribe_entero_y_prefiere_diarizacion(mono):
    plan = preparar(mono, "27.mp3", "izquierdo")
    assert plan.canales_audio == "mono"
    assert [p.contenido for p in plan.partes] == [mono]
    assert plan.prefiere_diarizacion and not plan.necesita_marcas
    assert plan.partes[0].hablante is None


def test_estereo_se_separa_por_canal(estereo):
    plan = preparar(estereo, "27.mp3", "derecho")
    assert plan.canales_audio == "estereo"
    assert [(p.hablante, p.nombre_archivo) for p in plan.partes] == [
        ("agente", "27-agente.mp3"),
        ("cliente", "27-cliente.mp3"),
    ]
    assert all(analizar(p.contenido).canales == 1 for p in plan.partes)
    assert plan.necesita_marcas and not plan.prefiere_diarizacion


def test_el_canal_del_agente_se_configura(estereo):
    izquierdo = preparar(estereo, "27.mp3", "izquierdo")
    derecho = preparar(estereo, "27.mp3", "derecho")
    assert izquierdo.partes[0].contenido == derecho.partes[1].contenido


def test_estereo_duplicado_pasa_a_mono(duplicado):
    plan = preparar(duplicado, "27.mp3", "izquierdo")
    assert plan.canales_audio == "estereo_duplicado"
    assert len(plan.partes) == 1 and analizar(plan.partes[0].contenido).canales == 1
    assert plan.prefiere_diarizacion


def test_como_mono_conserva_de_donde_vino(estereo):
    plan = como_mono(preparar(estereo, "27.mp3", "izquierdo"), estereo, "27.mp3")
    assert plan.canales_audio == "estereo" and len(plan.partes) == 1
    assert plan.partes[0].hablante is None


def test_partir_en_tramos_cuando_supera_el_tamaño():
    largo = a_mp3(wav(segundos=30), canales=1)
    audio = AudioPreparado(contenido=largo, nombre_archivo="x.mp3", tipo_mime="audio/mpeg",
                           duracion_s=30.0)
    assert partir(audio, len(largo) + 1) == [(0.0, audio)]

    tramos = partir(audio, len(largo) // 3)
    assert len(tramos) == 4
    assert [round(desde, 1) for desde, _ in tramos] == [0.0, 7.5, 15.0, 22.5]
    assert all(len(t.contenido) < len(largo) // 3 for _, t in tramos)
    assert sum(analizar(t.contenido).duracion_s for _, t in tramos) == pytest.approx(30, abs=1)
