"""Cuentas de cada plataforma, en la forma común `CuentaExterna`.

Los nombres de campos de cada API quedan encerrados aquí: el servicio de
cuentas no sabe que CloudTalk dice `firstname` y Chatwoot `available_name`.
"""

from pydantic import BaseModel, ConfigDict, field_validator

from reporte_cloudtalk import nombre_de_agente_catalogo


class CuentaExterna(BaseModel):
    model_config = ConfigDict(frozen=True)

    id_externo: str
    nombre: str
    correo: str | None = None

    @field_validator("correo")
    @classmethod
    def _normalizar_correo(cls, valor: str | None) -> str | None:
        return (valor or "").strip().lower() or None


def cuentas_de_cloudtalk(agentes: list[dict]) -> list[CuentaExterna]:
    """Agentes de `GET /agents/index.json`."""
    return [
        CuentaExterna(
            id_externo=str(agente["id"]),
            nombre=nombre_de_agente_catalogo(agente),
            correo=agente.get("email"),
        )
        for agente in agentes
        if agente.get("id") not in (None, "")
    ]


def cuentas_de_chatwoot(agentes: list[dict]) -> list[CuentaExterna]:
    """Usuarios de `GET /agents`."""
    cuentas = []
    for agente in agentes:
        if agente.get("id") in (None, ""):
            continue
        correo = (agente.get("email") or "").strip()
        nombre = (agente.get("available_name") or agente.get("name") or "").strip()
        cuentas.append(
            CuentaExterna(
                id_externo=str(agente["id"]),
                nombre=nombre or correo or f"Usuario {agente['id']}",
                correo=correo,
            )
        )
    return cuentas
