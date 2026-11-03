"""Login del único usuario del panel y protección de las rutas.

- La sesión es una cookie firmada con APP_COOKIE_KEY (HttpOnly, SameSite=Strict).
- Las peticiones que cambian algo deben traer la cabecera `X-Panel: 1`: un
  formulario de otro sitio no puede ponerla, así que no hay CSRF.
- Tras 5 intentos fallidos se bloquea el login 5 minutos.
"""

import secrets
import threading
import time

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

INTENTOS_MAXIMOS = 5
BLOQUEO_SEGUNDOS = 300
CABECERA = "x-panel"
METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}


class Credenciales(BaseModel):
    usuario: str
    contrasena: str


class Sesion(BaseModel):
    usuario: str


class Intentos:
    def __init__(self) -> None:
        self._fallidos: list[float] = []
        self._candado = threading.Lock()

    def bloqueado_hasta(self) -> float | None:
        with self._candado:
            ahora = time.monotonic()
            self._fallidos = [t for t in self._fallidos if ahora - t < BLOQUEO_SEGUNDOS]
            if len(self._fallidos) >= INTENTOS_MAXIMOS:
                return self._fallidos[0] + BLOQUEO_SEGUNDOS - ahora
            return None

    def fallo(self) -> int:
        with self._candado:
            self._fallidos.append(time.monotonic())
            return INTENTOS_MAXIMOS - len(self._fallidos)

    def exito(self) -> None:
        with self._candado:
            self._fallidos.clear()


def _contrasena_valida(contrasena: str, hash_guardado: str) -> bool:
    try:
        return bcrypt.checkpw(contrasena.encode(), hash_guardado.encode())
    except ValueError:
        return False


def usuario_actual(request: Request) -> str:
    """Dependencia de las rutas protegidas."""
    usuario = request.session.get("usuario")
    if not usuario:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Inicie sesión para continuar.")
    if request.method not in METODOS_SEGUROS and request.headers.get(CABECERA) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Petición rechazada.")
    return usuario


router = APIRouter(prefix="/api/sesion", tags=["sesión"])


@router.get("", response_model=Sesion)
def ver_sesion(usuario: str = Depends(usuario_actual)) -> Sesion:
    return Sesion(usuario=usuario)


@router.post("", response_model=Sesion)
def iniciar_sesion(datos: Credenciales, request: Request) -> Sesion:
    if request.headers.get(CABECERA) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Petición rechazada.")
    contenedor = request.app.state.contenedor
    intentos: Intentos = request.app.state.intentos
    if (espera := intentos.bloqueado_hasta()) is not None:
        minutos = max(1, round(espera / 60))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Demasiados intentos. Vuelva a probar en {minutos} min.",
        )
    cfg = contenedor.base
    usuario_ok = secrets.compare_digest(datos.usuario.strip(), cfg.usuario)
    if not (usuario_ok and _contrasena_valida(datos.contrasena, cfg.password_hash)):
        quedan = intentos.fallo()
        detalle = "El usuario o la contraseña no son correctos."
        if 0 < quedan < INTENTOS_MAXIMOS:
            detalle += f" Le quedan {quedan} intentos."
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detalle)
    intentos.exito()
    request.session.clear()
    request.session["usuario"] = cfg.usuario
    return Sesion(usuario=cfg.usuario)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def cerrar_sesion(request: Request) -> None:
    request.session.clear()
