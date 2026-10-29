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
    def __init__(self, sesion: Session, asignacion: ServicioAsignacion | None = None) -> None:
        self._sesion = sesion
        self._cuentas = RepositorioCuentas(sesion)
        self._reglas = RepositorioReglas(sesion)
        self._personas = RepositorioPersonas(sesion)
        # Se comparte con quien asigna, para que una regla creada aquí no
        # quede fuera de su caché.
        self._asignacion = asignacion or ServicioAsignacion(sesion)
        # Cuentas por plataforma ya leídas, para asegurar() en cada interacción.
        self._conocidas: dict[str, dict[str, Cuenta]] = {}

    def asegurar(self, plataforma: str, externa: CuentaExterna) -> Cuenta:
        """La cuenta con ese id externo; la crea si no existe.

        No pisa el nombre de una cuenta existente: el de la lista de agentes
        es más completo que el que viene en cada llamada.
        """
        if plataforma not in self._conocidas:
            self._conocidas[plataforma] = self._cuentas.de_plataforma(plataforma)
        cuenta = self._conocidas[plataforma].get(externa.id_externo)
        if cuenta is not None:
            return cuenta
        cuenta = self._cuentas.agregar(
            Cuenta(
                plataforma=plataforma,
                id_externo=externa.id_externo,
                nombre=externa.nombre,
                correo=externa.correo,
                activa=True,
            )
        )
        self._conocidas[plataforma][externa.id_externo] = cuenta
        if plataforma in PLATAFORMAS_CON_REGLA_POR_CORREO:
            self._crear_regla_por_correo(cuenta)
        return cuenta

    def actualizar(self, plataforma: str, externas: list[CuentaExterna]) -> ResumenCuentas:
        """Deja la tabla de cuentas igual a lo que devuelve la plataforma.

        Las cuentas que la plataforma ya no devuelve se desactivan, no se
        borran. Si la plataforma no devuelve ninguna, no se desactiva nada: es
        más probable un error de la API que una cuenta vacía.
        """
        if plataforma not in PLATAFORMAS:
            raise ValueError(f"Plataforma desconocida: {plataforma!r}")

        self._conocidas.pop(plataforma, None)
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
        return sum(
            self._crear_regla_por_correo(cuenta)
            for cuenta in self._cuentas.de_plataforma(plataforma).values()
            if cuenta.activa and cuenta.id not in con_reglas
        )

    def _crear_regla_por_correo(self, cuenta: Cuenta) -> bool:
        if not cuenta.correo:
            return False
        persona = self._personas.activa_por_correo(cuenta.correo)
        if persona is None:
            return False
        self._asignacion.crear_regla(
            cuenta.id, "dueno_unico", {"persona_id": persona.id}, DESDE_SIEMPRE
        )
        return True
