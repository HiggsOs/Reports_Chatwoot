"""Contrato común de las estrategias de asignación.

Una estrategia decide qué persona atendió una interacción a partir de la hora
local (España) y de los parámetros de la regla de la cuenta. No toca la base
ni convierte zonas horarias: eso lo hace el servicio, una sola vez para todas.
"""

from collections.abc import Mapping
from datetime import datetime, time
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

DIAS_SEMANA = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


class ResultadoAsignacion(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: int | None  # None: queda sin asignar
    motivo: str  # se le muestra al auditor


class Franja(BaseModel):
    """Días de la semana (0 = lunes) y un horario [inicio, fin) en hora local.

    No cruza la medianoche: un turno de 22:00 a 02:00 se carga como dos franjas.
    """

    model_config = ConfigDict(frozen=True)

    dias: tuple[int, ...]
    inicio: time
    fin: time

    @field_validator("dias")
    @classmethod
    def _dias_validos(cls, dias: tuple[int, ...]) -> tuple[int, ...]:
        if not dias:
            raise ValueError("la franja necesita al menos un día")
        if any(dia not in range(7) for dia in dias):
            raise ValueError("los días van de 0 (lunes) a 6 (domingo)")
        return tuple(sorted(set(dias)))

    @model_validator(mode="after")
    def _horario_valido(self) -> "Franja":
        if self.inicio >= self.fin:
            raise ValueError(
                f"la franja {self.inicio:%H:%M}–{self.fin:%H:%M} debe terminar "
                "después de empezar; si cruza la medianoche, cárguela como dos franjas"
            )
        return self

    def contiene(self, momento_local: datetime) -> bool:
        return (
            momento_local.weekday() in self.dias
            and self.inicio <= momento_local.time() < self.fin
        )

    def se_superpone_con(self, otra: "Franja") -> bool:
        return bool(set(self.dias) & set(otra.dias)) and (
            self.inicio < otra.fin and otra.inicio < self.fin
        )

    def describir(self) -> str:
        return f"{describir_dias(self.dias)} {self.inicio:%H:%M}–{self.fin:%H:%M}"


def describir_dias(dias: tuple[int, ...]) -> str:
    """(0, 1, 2, 3, 4, 6) → «lun–vie, dom»."""
    tramos: list[list[int]] = []
    for dia in dias:
        if tramos and dia == tramos[-1][-1] + 1:
            tramos[-1].append(dia)
        else:
            tramos.append([dia])
    partes = []
    for tramo in tramos:
        if len(tramo) >= 3:
            partes.append(f"{DIAS_SEMANA[tramo[0]]}–{DIAS_SEMANA[tramo[-1]]}")
        else:
            partes.extend(DIAS_SEMANA[dia] for dia in tramo)
    return ", ".join(partes)


def validar_sin_superposiciones(franjas: list[Franja]) -> None:
    for i, una in enumerate(franjas):
        for otra in franjas[i + 1 :]:
            if una.se_superpone_con(otra):
                raise ValueError(
                    f"las franjas «{una.describir()}» y «{otra.describir()}» se superponen"
                )


class EstrategiaAsignacion(Protocol):
    nombre: ClassVar[str]  # el que se guarda en la base; no cambia nunca
    titulo: ClassVar[str]
    descripcion: ClassVar[str]
    Parametros: ClassVar[type[BaseModel]]
    # Una estrategia retirada no se ofrece para reglas nuevas, pero sigue
    # sirviendo para las reglas históricas que la usan.
    retirada: ClassVar[bool]

    def asignar(self, momento_local: datetime, parametros) -> ResultadoAsignacion: ...

    def personas(self, parametros) -> set[int]:
        """Las personas que nombra la regla, para validarlas y mostrarlas."""
        ...

    def describir(self, parametros, nombres: Mapping[int, str]) -> list[str]:
        """Líneas legibles de la regla, con los nombres de las personas."""
        ...
