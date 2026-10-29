"""Una persona con horario fijo; todo lo que cae fuera es de la otra."""

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from panel.asignacion.base import Franja, ResultadoAsignacion, validar_sin_superposiciones
from panel.asignacion.registro import registrar


class ParametrosFijoYResto(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_fija_id: int
    franjas_fijas: list[Franja] = Field(min_length=1)
    persona_resto_id: int

    @model_validator(mode="after")
    def _validar(self) -> "ParametrosFijoYResto":
        if self.persona_fija_id == self.persona_resto_id:
            raise ValueError("la persona fija y la del resto deben ser distintas")
        validar_sin_superposiciones(self.franjas_fijas)
        return self


@registrar
class FijoYResto:
    nombre = "fijo_y_resto"
    titulo = "Horario fijo y el resto al otro"
    descripcion = (
        "Lo que cae dentro del horario de la persona fija es suyo; todo lo demás "
        "es de la otra persona. Nunca deja nada sin asignar."
    )
    Parametros = ParametrosFijoYResto
    retirada = False

    def asignar(
        self, momento_local: datetime, parametros: ParametrosFijoYResto
    ) -> ResultadoAsignacion:
        for franja in parametros.franjas_fijas:
            if franja.contiene(momento_local):
                return ResultadoAsignacion(
                    persona_id=parametros.persona_fija_id,
                    motivo=f"Dentro del horario fijo ({franja.describir()})",
                )
        return ResultadoAsignacion(
            persona_id=parametros.persona_resto_id, motivo="Fuera del horario fijo"
        )

    def personas(self, parametros: ParametrosFijoYResto) -> set[int]:
        return {parametros.persona_fija_id, parametros.persona_resto_id}

    def describir(
        self, parametros: ParametrosFijoYResto, nombres: Mapping[int, str]
    ) -> list[str]:
        fija = nombres.get(parametros.persona_fija_id, "?")
        resto = nombres.get(parametros.persona_resto_id, "?")
        lineas = [f"{fija}: {franja.describir()}" for franja in parametros.franjas_fijas]
        lineas.append(f"{resto}: todo lo demás")
        return lineas
