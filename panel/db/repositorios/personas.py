"""Consultas sobre los asesores."""

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from panel.db.modelos import Persona
from panel.esquemas.personas import AsesorArea, PersonaResumida, ResumenSincronizacion


class RepositorioPersonas:
    def __init__(self, sesion: Session) -> None:
        self._sesion = sesion

    def hay_personas(self) -> bool:
        return bool(self._sesion.scalar(select(exists().select_from(Persona))))

    def listar(self, solo_activas: bool = True) -> list[PersonaResumida]:
        consulta = select(Persona).order_by(Persona.nombre, Persona.correo)
        if solo_activas:
            consulta = consulta.where(Persona.activa)
        return [
            PersonaResumida.model_validate(persona, from_attributes=True)
            for persona in self._sesion.scalars(consulta)
        ]

    def por_ids(self, ids: set[int]) -> dict[int, PersonaResumida]:
        if not ids:
            return {}
        return {
            persona.id: PersonaResumida.model_validate(persona, from_attributes=True)
            for persona in self._sesion.scalars(select(Persona).where(Persona.id.in_(ids)))
        }

    def activa_por_correo(self, correo: str) -> PersonaResumida | None:
        persona = self._sesion.scalar(
            select(Persona).where(Persona.correo == correo.strip().lower(), Persona.activa)
        )
        return PersonaResumida.model_validate(persona, from_attributes=True) if persona else None

    def mapa_areas(self) -> dict[str, str]:
        """Correo → área de los asesores activos, ordenado por correo."""
        filas = self._sesion.execute(
            select(Persona.correo, Persona.area)
            .where(Persona.activa)
            .order_by(Persona.correo)
        )
        return {correo: area for correo, area in filas}

    def sincronizar_areas(self, asesores: list[AsesorArea]) -> ResumenSincronizacion:
        """Deja activos exactamente los asesores de la lista, con su área y nombre.

        Los que faltan en la lista se desactivan en vez de borrarse.
        """
        deseados = {asesor.correo: asesor for asesor in asesores}
        if len(deseados) != len(asesores):
            raise ValueError("Hay correos repetidos en la lista de asesores.")

        existentes = {
            persona.correo: persona
            for persona in self._sesion.scalars(select(Persona))
        }
        resumen = ResumenSincronizacion()

        for correo, asesor in deseados.items():
            persona = existentes.get(correo)
            if persona is None:
                self._sesion.add(
                    Persona(correo=correo, area=asesor.area, nombre=asesor.nombre, activa=True)
                )
                resumen.creadas += 1
                continue
            if not persona.activa:
                persona.activa = True
                resumen.reactivadas += 1
            if (persona.area, persona.nombre) != (asesor.area, asesor.nombre):
                persona.area = asesor.area
                persona.nombre = asesor.nombre
                resumen.actualizadas += 1

        for correo, persona in existentes.items():
            if correo not in deseados and persona.activa:
                persona.activa = False
                resumen.desactivadas += 1

        self._sesion.flush()
        return resumen
