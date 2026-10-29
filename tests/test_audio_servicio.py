import shutil
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from cloudtalk import CloudTalkError, GrabacionVencida
from config import ConfigError, cargar_config
from panel.audio.almacen import AlmacenError, AlmacenLocal
from panel.audio.conversion import analizar
from panel.audio.servicio import ServicioAudio
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import AudioPendiente, Llamada, PuntoSincronizacion
from panel.fuentes.cuentas import CuentaExterna
from panel.fuentes.interacciones import LlamadaExterna
from panel.servicios.interacciones import ServicioInteracciones
from panel.sync.tareas import RetencionDeAudios, SubirAudiosPendientes
from tests.audio_de_prueba import wav
from tests.test_config import ENTORNO_VALIDO

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Falta ffmpeg.")

UTC = timezone.utc
AHORA = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


class FuenteFalsa:
    def __init__(self, audio=None, error=None):
        self.audio = audio
        self.error = error
        self.pedidas = []

    def grabacion(self, id_externo):
        self.pedidas.append(id_externo)
        if self.error:
            raise self.error
        return self.audio


class AlmacenQueFalla(AlmacenLocal):
    def __init__(self, directorio):
        super().__init__(directorio)
        self.falla = True

    def subir(self, ruta, contenido):
        if self.falla:
            raise AlmacenError("el servidor no responde")
        super().subir(ruta, contenido)


def guardar_llamada(fabrica, id_externo="27", dias_atras=1, grabada=True):
    with unidad_de_trabajo(fabrica) as sesion:
        ServicioInteracciones(sesion).guardar_llamadas(
            [
                LlamadaExterna(
                    id_externo=id_externo,
                    agente=CuentaExterna(id_externo="100", nombre="Asesor"),
                    inicio=AHORA - timedelta(days=dias_atras),
                    duracion_s=60,
                    direccion="entrante",
                    grabada=grabada,
                    enlace_plataforma=None,
                    telefono_cliente=None,
                    nombre_cliente=None,
                    datos_origen={},
                )
            ]
        )
        return sesion.scalar(select(Llamada.id).where(Llamada.id_externo == id_externo))


def llamada(fabrica, llamada_id):
    with unidad_de_trabajo(fabrica) as sesion:
        fila = sesion.get(Llamada, llamada_id)
        return fila.audio_estado, fila.audio_ruta, fila.audio_canales


def pendientes(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        return sesion.scalar(select(func.count()).select_from(AudioPendiente))


def servicio(fabrica, fuente, almacen, ahora=AHORA):
    return ServicioAudio(fabrica, fuente, almacen, 90, ahora=lambda: ahora)


@pytest.fixture
def almacen(tmp_path):
    return AlmacenLocal(tmp_path / "audios")


def test_la_primera_escucha_trae_convierte_y_guarda(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    fuente = FuenteFalsa(wav(segundos=3))
    audio = servicio(fabrica, fuente, almacen)

    resultado = audio.escuchar(llamada_id)
    assert resultado.mp3 and analizar(resultado.mp3).canales == 1
    assert resultado.pendiente_de_subir
    assert llamada(fabrica, llamada_id) == ("pendiente", "cloudtalk/2026/11/27.mp3", 1)
    assert pendientes(fabrica) == 1

    assert audio.subir_pendiente(llamada_id)
    assert llamada(fabrica, llamada_id)[0] == "guardado"
    assert pendientes(fabrica) == 0
    assert almacen.bajar("cloudtalk/2026/11/27.mp3") == resultado.mp3


def test_la_segunda_escucha_sale_del_almacen_sin_pedirla_otra_vez(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    fuente = FuenteFalsa(wav())
    audio = servicio(fabrica, fuente, almacen)
    primera = audio.escuchar(llamada_id)
    audio.subir_pendiente(llamada_id)

    segunda = audio.escuchar(llamada_id)
    assert segunda.mp3 == primera.mp3
    assert not segunda.pendiente_de_subir
    assert fuente.pedidas == ["27"]


def test_un_estereo_se_guarda_en_estereo(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    resultado = servicio(fabrica, FuenteFalsa(wav(canales=2)), almacen).escuchar(llamada_id)
    assert analizar(resultado.mp3).canales == 2
    assert llamada(fabrica, llamada_id)[2] == 2


def test_sin_grabacion_y_grabacion_vencida_no_se_vuelven_a_pedir(fabrica, almacen):
    sin = guardar_llamada(fabrica, "1")
    vencida = guardar_llamada(fabrica, "2")
    fuente_sin = FuenteFalsa(None)
    fuente_vencida = FuenteFalsa(error=GrabacionVencida("410"))

    for _ in range(2):
        assert "no tiene grabación" in servicio(fabrica, fuente_sin, almacen).escuchar(sin).mensaje
        assert "ya borró" in servicio(fabrica, fuente_vencida, almacen).escuchar(vencida).mensaje
    assert fuente_sin.pedidas == ["1"] and fuente_vencida.pedidas == ["2"]
    assert llamada(fabrica, sin)[0] == "sin_grabacion"
    assert llamada(fabrica, vencida)[0] == "vencido"


def test_una_llamada_no_grabada_no_se_pide(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica, grabada=False)
    fuente = FuenteFalsa(wav())
    assert servicio(fabrica, fuente, almacen).escuchar(llamada_id).mensaje == "La llamada no se grabó."
    assert fuente.pedidas == []


def test_un_error_de_cloudtalk_no_marca_nada(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    resultado = servicio(fabrica, FuenteFalsa(error=CloudTalkError("caído")), almacen).escuchar(
        llamada_id
    )
    assert "caído" in resultado.mensaje and resultado.mp3 is None
    assert llamada(fabrica, llamada_id)[0] is None


def test_sin_almacen_se_escucha_pero_no_se_guarda(fabrica):
    llamada_id = guardar_llamada(fabrica)
    resultado = servicio(fabrica, FuenteFalsa(wav()), None).escuchar(llamada_id)
    assert resultado.mp3 and not resultado.pendiente_de_subir
    assert "no se guarda" in resultado.mensaje
    assert llamada(fabrica, llamada_id)[0] is None and pendientes(fabrica) == 0


def test_si_falla_la_subida_queda_pendiente_y_se_reintenta(fabrica, tmp_path):
    llamada_id = guardar_llamada(fabrica)
    almacen = AlmacenQueFalla(tmp_path / "audios")
    audio = servicio(fabrica, FuenteFalsa(wav()), almacen)
    primera = audio.escuchar(llamada_id)

    assert not audio.subir_pendiente(llamada_id)
    # Mientras tanto se escucha desde la base, sin volver a CloudTalk.
    assert audio.escuchar(llamada_id).mp3 == primera.mp3
    with unidad_de_trabajo(fabrica) as sesion:
        fila = sesion.get(AudioPendiente, llamada_id)
        assert (fila.intentos, fila.ultimo_error) == (1, "el servidor no responde")

    almacen.falla = False
    assert audio.subir_pendientes().model_dump() == {"subidos": 1, "fallidos": 0}
    assert llamada(fabrica, llamada_id)[0] == "guardado"


def test_si_el_almacen_pierde_el_archivo_se_trae_de_nuevo(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    fuente = FuenteFalsa(wav())
    audio = servicio(fabrica, fuente, almacen)
    audio.escuchar(llamada_id)
    audio.subir_pendiente(llamada_id)
    almacen.borrar("cloudtalk/2026/11/27.mp3")

    resultado = audio.escuchar(llamada_id)
    assert resultado.mp3 and "se trajo de nuevo" in resultado.mensaje
    assert len(fuente.pedidas) == 2


def test_retencion_conserva_el_dia_90_y_borra_desde_el_91(fabrica, almacen):
    dia_90 = guardar_llamada(fabrica, "90", dias_atras=90)
    dia_91 = guardar_llamada(fabrica, "91", dias_atras=91)
    # Se escucharon hace una semana, cuando todavía estaban dentro del plazo.
    antes = servicio(fabrica, FuenteFalsa(wav()), almacen, ahora=AHORA - timedelta(days=7))
    for llamada_id in (dia_90, dia_91):
        antes.escuchar(llamada_id)
        assert antes.subir_pendiente(llamada_id)

    resumen = servicio(fabrica, FuenteFalsa(), almacen).aplicar_retencion()

    assert resumen.model_dump() == {"borrados": 1, "fallidos": 0}
    assert llamada(fabrica, dia_90)[0] == "guardado"
    assert almacen.existe(llamada(fabrica, dia_90)[1])
    assert llamada(fabrica, dia_91)[:2] == ("eliminado", None)
    assert not almacen.existe("cloudtalk/2026/08/91.mp3")


def test_una_llamada_vieja_se_escucha_pero_no_se_guarda(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica, dias_atras=120)
    resultado = servicio(fabrica, FuenteFalsa(wav()), almacen).escuchar(llamada_id)
    assert resultado.mp3 and not resultado.pendiente_de_subir
    assert "se borra a los 90 días" in resultado.mensaje
    assert llamada(fabrica, llamada_id)[0] is None


def test_las_tareas_suben_pendientes_y_la_retencion_corre_una_vez_por_dia(fabrica, tmp_path):
    llamada_id = guardar_llamada(fabrica)
    almacen = AlmacenQueFalla(tmp_path / "audios")
    audio = servicio(fabrica, FuenteFalsa(wav()), almacen)
    audio.escuchar(llamada_id)
    almacen.falla = False

    resultado = SubirAudiosPendientes(fabrica, audio, ahora=lambda: AHORA).ejecutar()
    assert resultado.resumen == {"subidos": 1, "fallidos": 0}

    retencion = RetencionDeAudios(fabrica, audio, ahora=lambda: AHORA)
    assert retencion.ejecutar().resumen == {"borrados": 0, "fallidos": 0}
    assert retencion.ejecutar().resumen == {"omitida": True}
    mañana = RetencionDeAudios(fabrica, audio, ahora=lambda: AHORA + timedelta(days=1))
    assert "omitida" not in mañana.ejecutar().resumen
    with unidad_de_trabajo(fabrica) as sesion:
        assert sesion.get(PuntoSincronizacion, "retencion_audios").ultimo_exito is not None


# --- Configuración ----------------------------------------------------------


def test_sin_almacen_por_defecto():
    cfg = cargar_config(ENTORNO_VALIDO)
    assert (cfg.almacen_tipo, cfg.audio_retencion_dias, cfg.ftp_port) == ("", 90, 22)


def test_sftp_exige_sus_datos():
    with pytest.raises(ConfigError) as error:
        cargar_config({**ENTORNO_VALIDO, "ALMACEN_TIPO": "sftp", "FTP_HOST": "ftp.e.com"})
    mensaje = str(error.value)
    assert "FTP_USER" in mensaje and "FTP_PASSWORD" in mensaje and "SFTP_HUELLA_HOST" in mensaje
    assert "FTP_HOST" not in mensaje.split("faltan:")[1]


def test_sftp_completo():
    cfg = cargar_config(
        {
            **ENTORNO_VALIDO,
            "ALMACEN_TIPO": " SFTP ",
            "FTP_HOST": "ftp.e.com",
            "FTP_PORT": "8023",
            "FTP_USER": "audios@e.com",
            "FTP_PASSWORD": " clave con espacios ",
            "FTP_DIR": "/grabaciones",
            "SFTP_HUELLA_HOST": "SHA256:abc",
        }
    )
    assert (cfg.almacen_tipo, cfg.ftp_port, cfg.ftp_dir) == ("sftp", 8023, "/grabaciones")
    assert cfg.ftp_password == " clave con espacios "


def test_almacen_desconocido():
    with pytest.raises(ConfigError, match="ALMACEN_TIPO"):
        cargar_config({**ENTORNO_VALIDO, "ALMACEN_TIPO": "ftp"})
