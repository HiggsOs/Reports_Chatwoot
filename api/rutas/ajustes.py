"""General: conexiones con CloudTalk, Chatwoot y el almacén de audios."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.contenedor import Contenedor
from api.dependencias import contenedor
from api.rutas.transcripcion import Prueba, guardar
from chatwoot import ChatwootError, ClienteChatwoot
from cloudtalk import ClienteCloudTalk, CloudTalkError
from config import ruta_audios_locales
from panel.ajustes import CAMPOS, enmascarar, origenes
from panel.audio.almacen import AlmacenError, AlmacenLocal, AlmacenSFTP, obtener_huella

router = APIRouter(prefix="/api/ajustes", tags=["ajustes"])

# Lo que se edita en General. Lo de transcripción tiene su propia pantalla.
GENERALES = (
    "CLOUDTALK_API_KEY_ID", "CLOUDTALK_API_KEY_SECRET",
    "CHATWOOT_BASE_URL", "CHATWOOT_ACCOUNT_ID", "CHATWOOT_API_TOKEN", "CHATWOOT_DIAS_RELECTURA",
    "ALMACEN_TIPO", "FTP_HOST", "FTP_PORT", "FTP_USER", "FTP_PASSWORD", "FTP_DIR",
    "SFTP_HUELLA_HOST", "AUDIO_RETENCION_DIAS",
    "SYNC_INTERVALO_MINUTOS", "SYNC_DIAS_INICIALES",
)
ARCHIVO_DE_PRUEBA = "prueba-del-panel/conexion.txt"


class Valor(BaseModel):
    valor: str  # los secretos, enmascarados
    secreto: bool
    origen: str | None  # «panel», «entorno» o nada


@router.get("/general", response_model=dict[str, Valor])
def ver(c: Contenedor = Depends(contenedor)) -> dict[str, Valor]:
    efectivo = {**c.entorno, **c.lectura.valores}
    origen = origenes(c.entorno, c.lectura)
    resultado = {}
    for clave in GENERALES:
        valor = (efectivo.get(clave) or "").strip()
        secreto = CAMPOS[clave].secreto
        resultado[clave] = Valor(valor=enmascarar(valor) if secreto else valor, secreto=secreto, origen=origen.get(clave))
    return resultado


class Cambios(BaseModel):
    """Solo las claves que cambian. En un secreto, «» o ausente deja el guardado."""

    valores: dict[str, str]


@router.put("/general", status_code=204)
def guardar_general(datos: Cambios, c: Contenedor = Depends(contenedor)) -> None:
    ajenas = [k for k in datos.valores if k not in GENERALES]
    if ajenas:
        raise HTTPException(422, "No se pueden cambiar aquí: " + ", ".join(sorted(ajenas)))
    cambios: dict[str, str | None] = {}
    for clave, valor in datos.valores.items():
        valor = valor if CAMPOS[clave].secreto else valor.strip()
        if CAMPOS[clave].secreto and not valor:
            continue
        cambios[clave] = valor or None
    guardar(c, cambios)


def _valores(c: Contenedor, datos: Cambios) -> dict[str, str]:
    """Lo vigente con lo que se está probando encima (un secreto vacío no pisa)."""
    valores = {**c.entorno, **c.lectura.valores}
    for clave, valor in datos.valores.items():
        if valor.strip():
            secreto = clave in CAMPOS and CAMPOS[clave].secreto
            valores[clave] = valor if secreto else valor.strip()
    return valores


@router.post("/probar/cloudtalk", response_model=Prueba)
def probar_cloudtalk(datos: Cambios, c: Contenedor = Depends(contenedor)) -> Prueba:
    v = _valores(c, datos)
    if not (v.get("CLOUDTALK_API_KEY_ID") and v.get("CLOUDTALK_API_KEY_SECRET")):
        return Prueba(ok=False, mensaje="Complete el ID y la clave secreta para probar.")
    try:
        agentes = ClienteCloudTalk(
            v["CLOUDTALK_API_KEY_ID"], v["CLOUDTALK_API_KEY_SECRET"], c.cfg.cloudtalk_base_url, intentos_limite=1
        ).listar_agentes()
    except CloudTalkError as error:
        return Prueba(ok=False, mensaje=f"CloudTalk rechazó la conexión: {error}")
    return Prueba(ok=True, mensaje=f"Conexión correcta: CloudTalk tiene {len(agentes)} agentes.")


@router.post("/probar/chatwoot", response_model=Prueba)
def probar_chatwoot(datos: Cambios, c: Contenedor = Depends(contenedor)) -> Prueba:
    v = _valores(c, datos)
    url, cuenta, token = (v.get(k, "").strip() for k in ("CHATWOOT_BASE_URL", "CHATWOOT_ACCOUNT_ID", "CHATWOOT_API_TOKEN"))
    if not (url and cuenta.isdigit() and token):
        return Prueba(ok=False, mensaje="Complete la URL, el ID de la cuenta (un número) y el token para probar.")
    try:
        bandejas = ClienteChatwoot(url.rstrip("/"), int(cuenta), token).listar_inboxes()
    except ChatwootError as error:
        return Prueba(ok=False, mensaje=f"Chatwoot rechazó la conexión: {error}")
    return Prueba(ok=True, mensaje="Conexión correcta. Bandejas visibles: " + (", ".join(bandejas.values()) or "ninguna") + ".")


@router.post("/probar/almacen", response_model=Prueba)
def probar_almacen(datos: Cambios, c: Contenedor = Depends(contenedor)) -> Prueba:
    v = _valores(c, datos)
    tipo = (datos.valores.get("ALMACEN_TIPO", v.get("ALMACEN_TIPO", "")) or "").strip()
    if tipo == "":
        return Prueba(ok=True, mensaje="Sin almacén no hay nada que probar: los audios se escuchan sin guardarse.")
    if tipo == "sftp":
        faltan = [n for n, k in (("servidor", "FTP_HOST"), ("usuario", "FTP_USER"), ("contraseña", "FTP_PASSWORD"),
                                 ("huella", "SFTP_HUELLA_HOST")) if not v.get(k)]
        puerto = (v.get("FTP_PORT") or "22").strip()
        if faltan or not puerto.isdigit():
            return Prueba(ok=False, mensaje="Para probar faltan: " + ", ".join(faltan or ["un puerto numérico"]) + ".")
        almacen = AlmacenSFTP(v["FTP_HOST"], int(puerto), v["FTP_USER"], v["FTP_PASSWORD"],
                              v.get("FTP_DIR") or "/", v["SFTP_HUELLA_HOST"])
    else:
        almacen = AlmacenLocal(ruta_audios_locales(c.cfg))
    try:
        almacen.subir(ARCHIVO_DE_PRUEBA, b"prueba del panel")
        leido = almacen.bajar(ARCHIVO_DE_PRUEBA)
        almacen.borrar(ARCHIVO_DE_PRUEBA)
    except AlmacenError as error:
        return Prueba(ok=False, mensaje=str(error))
    if leido != b"prueba del panel":
        return Prueba(ok=False, mensaje="Se escribió el archivo de prueba pero al leerlo volvió distinto.")
    return Prueba(ok=True, mensaje="Conexión correcta: se pudo escribir, leer y borrar un archivo de prueba.")


class Servidor(BaseModel):
    host: str
    puerto: int


class Huella(BaseModel):
    huella: str


@router.post("/huella", response_model=Huella)
def huella(datos: Servidor, _c: Contenedor = Depends(contenedor)) -> Huella:
    try:
        return Huella(huella=obtener_huella(datos.host.strip(), datos.puerto))
    except Exception as error:  # noqa: BLE001 — cualquier fallo de red se informa igual
        raise HTTPException(502, f"No se pudo leer la huella: {error}") from error
