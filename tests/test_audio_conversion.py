import shutil

import pytest

from panel.audio.conversion import AudioInvalido, a_mp3, analizar
from tests.audio_de_prueba import wav

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="Falta ffmpeg."
)


def test_analiza_un_wav_mono():
    info = analizar(wav(segundos=2.0, canales=1))
    assert info.canales == 1
    assert info.frecuencia_hz == 8000
    assert info.duracion_s == pytest.approx(2.0, abs=0.05)


def test_analiza_un_wav_estereo():
    assert analizar(wav(canales=2)).canales == 2


def test_un_mono_queda_mono_y_mucho_mas_chico():
    original = wav(segundos=10.0)
    mp3 = a_mp3(original, canales=1)
    assert mp3[:3] == b"ID3" or mp3[:2] == b"\xff\xf3" or mp3[0] == 0xFF
    assert len(mp3) < len(original) / 3
    assert analizar(mp3).canales == 1


def test_un_estereo_conserva_los_dos_canales():
    mp3 = a_mp3(wav(segundos=3.0, canales=2), canales=2)
    info = analizar(mp3)
    assert info.canales == 2
    assert info.duracion_s == pytest.approx(3.0, abs=0.2)


def test_un_archivo_que_no_es_audio():
    with pytest.raises(AudioInvalido):
        analizar(b"esto no es un wav")
    with pytest.raises(AudioInvalido):
        a_mp3(b"esto no es un wav", canales=1)
