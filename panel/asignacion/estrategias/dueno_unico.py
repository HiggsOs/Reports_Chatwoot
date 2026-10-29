"""Cuenta de una sola persona: todo es suyo."""

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from panel.asignacion.base import ResultadoAsignacion
from panel.asignacion.registro import registrar


class ParametrosDuenoUnico(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: int


@registrar
class DuenoUnico:
    nombre = "dueno_unico"
    titulo = "Una sola persona"
    descripcion = "Todas las llamadas o conversaciones de la cuenta son de una persona."
    Parametros = ParametrosDuenoUnico
    retirada = False

    def asignar(
        self, momento_local: datetime, parametros: ParametrosDuenoUnico
    ) -> ResultadoAsignacion:
        return ResultadoAsignacion(
            persona_id=parametros.persona_id, motivo="Cuenta de una sola persona"
        )

    def personas(self, parametros: ParametrosDuenoUnico) -> set[int]:
        return {parametros.persona_id}

    def describir(
        self, parametros: ParametrosDuenoUnico, nombres: Mapping[int, str]
    ) -> list[str]:
        return [f"Todo para {nombres.get(parametros.persona_id, '?')}"]
