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
    nombre: str | None = None

    @field_validator("correo")
    @classmethod
    def _normalizar_correo(cls, valor: str) -> str:
        limpio = valor.strip().lower()
        if not limpio:
            raise ValueError("el correo no puede estar vacío")
        return limpio

    @field_validator("nombre")
    @classmethod
    def _normalizar_nombre(cls, valor: str | None) -> str | None:
        return (valor or "").strip() or None


class PersonaResumida(BaseModel):
    """Lo que las pantallas necesitan de una persona para elegirla en una lista."""

    model_config = ConfigDict(frozen=True)

    id: int
    correo: str
    nombre: str | None
    area: str
    activa: bool

    @property
    def etiqueta(self) -> str:
        return self.nombre or self.correo


class ResumenSincronizacion(BaseModel):
    """Qué cambió al guardar la lista de asesores."""

    creadas: int = 0
    actualizadas: int = 0
    reactivadas: int = 0
    desactivadas: int = 0

    @property
    def hubo_cambios(self) -> bool:
        return any((self.creadas, self.actualizadas, self.reactivadas, self.desactivadas))
