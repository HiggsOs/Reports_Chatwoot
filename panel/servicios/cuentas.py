"""Alta y actualización de las cuentas de cada plataforma."""

from pydantic import BaseModel
from sqlalchemy.orm import Session

from panel.asignacion.servicio import DESDE_SIEMPRE, ServicioAsignacion
from panel.db.modelos import PLATAFORMAS, Cuenta
from panel.db.repositorios.cuentas import RepositorioCuentas, RepositorioReglas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.fuentes.cuentas import CuentaExterna

# En Chatwoot cada usuario es una persona (las bandejas son las compartidas),
# así que su regla se puede deducir del correo. En CloudTalk no: una cuenta
# compartida tiene el correo de una sola de las personas que la usan.
PLATAFORMAS_CON_REGLA_POR_CORREO = ("chatwoot",)


class ResumenCuentas(BaseModel):
    nuevas: int = 0
    actualizadas: int = 0
    reactivadas: int = 0
    desactivadas: int = 0
    reglas_automaticas: int = 0


class ServicioCuentas:
    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion
        self._cuentas = RepositorioCuentas(sesion)
        self._reglas = RepositorioReglas(sesion)
        self._personas = RepositorioPersonas(sesion)

    def actualizar(self, plataforma: str, externas: list[CuentaExterna]) -> ResumenCuentas:
        """Deja la tabla de cuentas igual a lo que devuelve la plataforma.

        Las cuentas que la plataforma ya no devuelve se desactivan, no se
        borran. Si la plataforma no devuelve ninguna, no se desactiva nada: es
        más probable un error de la API que una cuenta vacía.
        """
        if plataforma not in PLATAFORMAS:
            raise ValueError(f"Plataforma desconocida: {plataforma!r}")

        existentes = self._cuentas.de_plataforma(plataforma)
        resumen = ResumenCuentas()
        vistas: set[str] = set()

        for externa in externas:
            vistas.add(externa.id_externo)
            cuenta = existentes.get(externa.id_externo)
            if cuenta is None:
                self._cuentas.agregar(
                    Cuenta(
                        plataforma=plataforma,
                        id_externo=externa.id_externo,
                        nombre=externa.nombre,
                        correo=externa.correo,
                        activa=True,
                    )
                )
                resumen.nuevas += 1
                continue
            if not cuenta.activa:
                cuenta.activa = True
                resumen.reactivadas += 1
            if (cuenta.nombre, cuenta.correo) != (externa.nombre, externa.correo):
                cuenta.nombre = externa.nombre
                cuenta.correo = externa.correo
                resumen.actualizadas += 1

        if externas:
            for id_externo, cuenta in existentes.items():
                if id_externo not in vistas and cuenta.activa:
                    cuenta.activa = False
                    resumen.desactivadas += 1

        self._sesion.flush()
        if plataforma in PLATAFORMAS_CON_REGLA_POR_CORREO:
            resumen.reglas_automaticas = self._crear_reglas_por_correo(plataforma)
        return resumen

    def _crear_reglas_por_correo(self, plataforma: str) -> int:
        """A cada cuenta sin regla cuyo correo es el de una persona activa le
        crea una regla `dueno_unico` desde siempre."""
        con_reglas = self._reglas.cuentas_con_reglas()
        asignacion = ServicioAsignacion(self._sesion)
        creadas = 0
        for cuenta in self._cuentas.de_plataforma(plataforma).values():
            if not cuenta.activa or not cuenta.correo or cuenta.id in con_reglas:
                continue
            persona = self._personas.activa_por_correo(cuenta.correo)
            if persona is None:
                continue
            asignacion.crear_regla(
                cuenta.id, "dueno_unico", {"persona_id": persona.id}, DESDE_SIEMPRE
            )
            creadas += 1
        return creadas
