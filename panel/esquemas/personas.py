"""Esquemas de los asesores (personas reales)."""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, field_validator

Area = Literal["Comercial", "RDC"]
AREAS: tuple[str, ...] = get_args(Area)


class AsesorArea(BaseModel):
    """Un asesor con su área, tal como se edita en la pestaña Asesores."""

    model_config = ConfigDict(frozen=True)

    correo: str
    area: Area

    @field_validator("correo")
    @classmethod
    def _normalizar_correo(cls, valor: str) -> str:
        limpio = valor.strip().lower()
        if not limpio:
            raise ValueError("el correo no puede estar vacío")
        return limpio


class ResumenSincronizacion(BaseModel):
    """Qué cambió al guardar la lista de asesores."""

    creadas: int = 0
    actualizadas: int = 0
    reactivadas: int = 0
    desactivadas: int = 0

    @property
    def hubo_cambios(self) -> bool:
        return any((self.creadas, self.actualizadas, self.reactivadas, self.desactivadas))
