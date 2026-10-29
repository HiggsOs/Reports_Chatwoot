"""Pruebas de contrato de AlmacenAudio: corren contra cada implementación."""

import pytest

from panel.audio.almacen import (
    AlmacenError,
    AlmacenLocal,
    AlmacenSFTP,
    huella_sha256,
    obtener_huella,
)
from panel.audio.huella import main as huella_main
from tests.servidor_sftp import CLAVE, USUARIO, ServidorSFTP


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    servidor = ServidorSFTP(tmp_path_factory.mktemp("sftp"))
    yield servidor
    servidor.cerrar()


def sftp(servidor, huella=None, clave=CLAVE, directorio="/audios"):
    (servidor.raiz / "audios").mkdir(exist_ok=True)
    return AlmacenSFTP(
        "127.0.0.1",
        servidor.puerto,
        USUARIO,
        clave,
        directorio,
        huella or huella_sha256(servidor.clave_servidor),
    )


@pytest.fixture(params=["local", "sftp"])
def almacen(request, tmp_path, servidor):
    if request.param == "local":
        return AlmacenLocal(tmp_path / "audios")
    return sftp(servidor)


def test_subir_bajar_y_borrar(almacen):
    ruta = "cloudtalk/2026/10/27.mp3"
    assert not almacen.existe(ruta)
    almacen.subir(ruta, b"ID3 audio")
    assert almacen.existe(ruta)
    assert almacen.bajar(ruta) == b"ID3 audio"

    almacen.subir(ruta, b"ID3 otro")  # pisar lo que había
    assert almacen.bajar(ruta) == b"ID3 otro"

    almacen.borrar(ruta)
    assert not almacen.existe(ruta)
    almacen.borrar(ruta)  # borrar lo que ya no está no falla


def test_bajar_lo_que_no_existe_falla_con_un_error_del_almacen(almacen):
    with pytest.raises(AlmacenError):
        almacen.bajar("cloudtalk/no-existe.mp3")


@pytest.mark.parametrize("ruta", ["", "/etc/passwd", "../fuera.mp3", "a/../../b.mp3"])
def test_no_acepta_rutas_que_salgan_del_directorio(almacen, ruta):
    with pytest.raises(AlmacenError):
        almacen.subir(ruta, b"x")


def test_sftp_guarda_dentro_del_directorio_configurado(servidor):
    sftp(servidor).subir("cloudtalk/1.mp3", b"ID3")
    assert (servidor.raiz / "audios" / "cloudtalk" / "1.mp3").read_bytes() == b"ID3"


def test_sftp_no_envia_nada_si_la_huella_no_coincide(servidor):
    almacen = sftp(servidor, huella="SHA256:otra-huella")
    with pytest.raises(AlmacenError, match="huella"):
        almacen.subir("cloudtalk/2.mp3", b"ID3")
    assert not (servidor.raiz / "audios" / "cloudtalk" / "2.mp3").exists()


def test_sftp_acepta_la_huella_sin_prefijo(servidor):
    huella = huella_sha256(servidor.clave_servidor).removeprefix("SHA256:")
    sftp(servidor, huella=huella).subir("cloudtalk/3.mp3", b"ID3")


def test_sftp_con_clave_incorrecta(servidor):
    with pytest.raises(AlmacenError):
        sftp(servidor, clave="otra").existe("x.mp3")


def test_sftp_sin_servidor():
    almacen = AlmacenSFTP("127.0.0.1", 1, USUARIO, CLAVE, "/audios", "SHA256:x")
    with pytest.raises(AlmacenError):
        almacen.existe("x.mp3")


def test_obtener_huella(servidor, capsys):
    esperada = huella_sha256(servidor.clave_servidor)
    assert obtener_huella("127.0.0.1", servidor.puerto) == esperada
    assert huella_main(["127.0.0.1", str(servidor.puerto)]) == 0
    assert capsys.readouterr().out.strip() == esperada
    assert huella_main(["solo-host"]) == 2
