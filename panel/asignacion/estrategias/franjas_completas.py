"""Cada persona tiene sus franjas; lo que no cae en ninguna queda sin asignar."""

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from panel.asignacion.base import Franja, ResultadoAsignacion, validar_sin_superposiciones
from panel.asignacion.registro import registrar


class FranjaDePersona(Franja):
    persona_id: int


class ParametrosFranjasCompletas(BaseModel):
    model_config = ConfigDict(frozen=True)

    franjas: list[FranjaDePersona] = Field(min_length=1)

    @model_validator(mode="after")
    def _validar(self) -> "ParametrosFranjasCompletas":
        # Una superposición daría dos dueños a la misma llamada.
        validar_sin_superposiciones(self.franjas)
        return self


@registrar
class FranjasCompletas:
    nombre = "franjas_completas"
    titulo = "Franjas para cada persona"
    descripcion = (
        "Cada persona tiene sus franjas. Lo que no cae en ninguna queda sin "
        "asignar y va a la bandeja para elegir a mano."
    )
    Parametros = ParametrosFranjasCompletas
    retirada = False

    def asignar(
        self, momento_local: datetime, parametros: ParametrosFranjasCompletas
    ) -> ResultadoAsignacion:
        for franja in parametros.franjas:
            if franja.contiene(momento_local):
                return ResultadoAsignacion(
                    persona_id=franja.persona_id,
                    motivo=f"Dentro de su franja ({franja.describir()})",
                )
        return ResultadoAsignacion(persona_id=None, motivo="Fuera de todas las franjas")

    def personas(self, parametros: ParametrosFranjasCompletas) -> set[int]:
        return {franja.persona_id for franja in parametros.franjas}

    def describir(
        self, parametros: ParametrosFranjasCompletas, nombres: Mapping[int, str]
    ) -> list[str]:
        lineas = [
            f"{nombres.get(franja.persona_id, '?')}: {franja.describir()}"
            for franja in parametros.franjas
        ]
        lineas.append("Fuera de estas franjas: sin asignar")
        return lineas
