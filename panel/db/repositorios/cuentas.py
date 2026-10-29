"""Consultas sobre las cuentas de las plataformas y sus reglas de asignación."""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from panel.db.modelos import Cuenta, ReglaAsignacion


class RepositorioCuentas:
    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def obtener(self, cuenta_id: int) -> Cuenta | None:
        return self._sesion.get(Cuenta, cuenta_id)

    def de_plataforma(self, plataforma: str) -> dict[str, Cuenta]:
        """id externo → cuenta, activas o no."""
        return {
            cuenta.id_externo: cuenta
            for cuenta in self._sesion.scalars(
                select(Cuenta).where(Cuenta.plataforma == plataforma)
            )
        }

    def listar(self, incluir_inactivas: bool = False) -> list[Cuenta]:
        consulta = select(Cuenta).order_by(Cuenta.plataforma, Cuenta.nombre)
        if not incluir_inactivas:
            consulta = consulta.where(Cuenta.activa)
        return list(self._sesion.scalars(consulta))

    def agregar(self, cuenta: Cuenta) -> Cuenta:
        self._sesion.add(cuenta)
        self._sesion.flush()
        return cuenta


class RepositorioReglas:
    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def vigente(self, cuenta_id: int, momento: datetime) -> ReglaAsignacion | None:
        """La regla que regía en ese momento: desde incluido, hasta excluido."""
        return self._sesion.scalar(
            select(ReglaAsignacion).where(
                ReglaAsignacion.cuenta_id == cuenta_id,
                ReglaAsignacion.vigente_desde <= momento,
                or_(
                    ReglaAsignacion.vigente_hasta.is_(None),
                    ReglaAsignacion.vigente_hasta > momento,
                ),
            )
        )

    def ultima(self, cuenta_id: int) -> ReglaAsignacion | None:
        return self._sesion.scalar(
            select(ReglaAsignacion)
            .where(ReglaAsignacion.cuenta_id == cuenta_id)
            .order_by(ReglaAsignacion.vigente_desde.desc(), ReglaAsignacion.id.desc())
            .limit(1)
        )

    def historial(self, cuenta_id: int) -> list[ReglaAsignacion]:
        """De la más reciente a la más antigua."""
        return list(
            self._sesion.scalars(
                select(ReglaAsignacion)
                .where(ReglaAsignacion.cuenta_id == cuenta_id)
                .order_by(ReglaAsignacion.vigente_desde.desc(), ReglaAsignacion.id.desc())
            )
        )

    def cuentas_con_reglas(self) -> set[int]:
        return set(self._sesion.scalars(select(ReglaAsignacion.cuenta_id).distinct()))

    def agregar(self, regla: ReglaAsignacion) -> ReglaAsignacion:
        self._sesion.add(regla)
        self._sesion.flush()
        return regla
