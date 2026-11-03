"""Dependencias comunes de las rutas: el contenedor y una sesión de base."""

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from api.contenedor import Contenedor
from api.seguridad import usuario_actual
from panel.db.base import unidad_de_trabajo


def contenedor(request: Request, _usuario: str = Depends(usuario_actual)) -> Contenedor:
    """El contenedor, solo para peticiones con sesión iniciada."""
    return request.app.state.contenedor


def sesion(c: Contenedor = Depends(contenedor)) -> Iterator[Session]:
    """Una unidad de trabajo por petición: confirma al terminar, o deshace."""
    with unidad_de_trabajo(c.fabrica) as s:
        yield s
