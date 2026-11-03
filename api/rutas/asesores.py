"""Asesores: las personas reales, con su área. No se borran: se desactivan."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from api.dependencias import sesion
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea, PersonaResumida, ResumenSincronizacion

router = APIRouter(prefix="/api/asesores", tags=["asesores"])


@router.get("", response_model=list[PersonaResumida])
def listar(inactivos: bool = False, s: Session = Depends(sesion)) -> list[PersonaResumida]:
    return RepositorioPersonas(s).listar(solo_activas=not inactivos)


class Lista(BaseModel):
    """La lista completa de asesores activos: los que faltan se desactivan."""

    asesores: list[dict]


@router.put("", response_model=ResumenSincronizacion)
def guardar(datos: Lista, s: Session = Depends(sesion)) -> ResumenSincronizacion:
    try:
        asesores = [AsesorArea.model_validate(a) for a in datos.asesores]
    except ValidationError as error:
        raise HTTPException(422, "Revise los datos: cada asesor necesita un correo válido y el área Comercial o RDC.") from error
    correos = [a.correo for a in asesores]
    if len(correos) != len(set(correos)):
        raise HTTPException(422, "Hay correos repetidos. Cada asesor debe aparecer una sola vez.")
    return RepositorioPersonas(s).sincronizar_areas(asesores)
