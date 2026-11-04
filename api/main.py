"""Aplicación FastAPI: la API del panel y el frontend de React ya compilado.

En producción: `uvicorn api.main:crear_app --factory`. Sirve `/api/...` y, para cualquier otra
ruta, el `index.html` de `web/dist`, así funcionan las direcciones del
frontend (`/llamadas`, `/transcripcion`…) al recargar la página.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware

from api import seguridad
from api.contenedor import Contenedor
from api.rutas import ajustes, asesores, cuentas, inicio, interacciones, reportes, transcripcion

registro = logging.getLogger(__name__)

WEB = Path(__file__).resolve().parents[1] / "web" / "dist"
DURACION_SESION = 7 * 24 * 3600


def crear_app(contenedor: Contenedor | None = None, web: Path = WEB) -> FastAPI:
    if contenedor is None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        contenedor = Contenedor()
    app = FastAPI(title="Panel de calidad", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json")
    app.state.contenedor = contenedor
    app.state.intentos = seguridad.Intentos()
    app.state.reportes = reportes.Reportes()
    app.add_middleware(
        SessionMiddleware,
        secret_key=contenedor.base.cookie_key,
        session_cookie="panel_sesion",
        max_age=DURACION_SESION,
        same_site="strict",
        # Detrás de HTTPS (EasyPanel). En desarrollo local: PANEL_COOKIE_SEGURA=0.
        https_only=contenedor.entorno.get("PANEL_COOKIE_SEGURA", "1") != "0",
    )

    @app.exception_handler(SQLAlchemyError)
    async def base_caida(_request: Request, _error: SQLAlchemyError):
        registro.exception("Error de base de datos")
        return JSONResponse(
            {"detail": "No se pudo leer la base de datos. Recargue la página; si sigue, revise el log del servicio."},
            status_code=503,
        )

    @app.get("/api/salud", include_in_schema=False)
    def salud() -> dict:
        return {"ok": True}

    for modulo in (seguridad, inicio, interacciones, transcripcion, ajustes, cuentas, asesores, reportes):
        app.include_router(modulo.router)

    @app.api_route("/api/{_resto:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
    def no_existe(_resto: str):
        raise HTTPException(404, "No existe.")

    @app.middleware("http")
    async def cache_de_recursos(request: Request, siguiente):
        respuesta = await siguiente(request)
        # Los archivos de /assets llevan un hash en el nombre: no cambian nunca.
        if request.url.path.startswith("/assets/") and respuesta.status_code == 200:
            respuesta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return respuesta

    if (web / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")
        indice = web / "index.html"

        @app.get("/{ruta:path}", include_in_schema=False)
        def frontend(ruta: str):
            archivo = (web / ruta).resolve()
            if ruta and archivo.is_file() and web.resolve() in archivo.parents:
                return FileResponse(archivo)
            return FileResponse(indice, headers={"Cache-Control": "no-cache"})

    return app
