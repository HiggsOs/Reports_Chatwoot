"""Guardado y asignación de llamadas y conversaciones."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from panel.asignacion.servicio import (
    ZONA_OPERACION_POR_DEFECTO,
    AsignacionResuelta,
    ServicioAsignacion,
)
from panel.db.modelos import (
    ASIGNACION_AUTOMATICA,
    ASIGNACION_MANUAL,
    Cliente,
    Conversacion,
    Llamada,
)
from panel.db.repositorios.personas import RepositorioPersonas
from panel.fuentes.interacciones import ConversacionExterna, LlamadaExterna
from panel.servicios.cuentas import ServicioCuentas
from panel.telefonos import normalizar
from reporte import INDETERMINADO, detectar_cierre, detectar_direccion

MOTIVO_SIN_USUARIO = "La conversación no tiene usuario asignado en Chatwoot"
MOTIVO_MANUAL = "Asignada a mano"
SIN_ASIGNAR = "Sin asignar"

Tipo = Literal["llamada", "conversacion"]
MODELOS = {"llamada": Llamada, "conversacion": Conversacion}


class ResumenGuardado(BaseModel):
    nuevas: int = 0
    actualizadas: int = 0
    sin_asignar: int = 0


class ResumenReasignacion(BaseModel):
    revisadas: int = 0
    cambiaron: int = 0
    # Etiqueta de la persona (o «Sin asignar») → cantidad, tras reasignar.
    por_persona: dict[str, int] = {}


class ServicioInteracciones:
    def __init__(self, sesion: Session, zona=ZONA_OPERACION_POR_DEFECTO) -> None:
        self._sesion = sesion
        self.asignacion = ServicioAsignacion(sesion, zona)
        self._cuentas = ServicioCuentas(sesion, self.asignacion)
        self._personas = RepositorioPersonas(sesion)

    # --- Guardado ------------------------------------------------------------

    def guardar_llamadas(self, llamadas: list[LlamadaExterna]) -> ResumenGuardado:
        resumen = ResumenGuardado()
        existentes = self._existentes(Llamada, [ll.id_externo for ll in llamadas])
        for externa in llamadas:
            cuenta = self._cuentas.asegurar("cloudtalk", externa.agente)
            llamada = existentes.get(externa.id_externo)
            nueva = llamada is None
            if nueva:
                llamada = Llamada(id_externo=externa.id_externo, asignacion=ASIGNACION_AUTOMATICA)
            llamada.cuenta_id = cuenta.id
            llamada.inicio = externa.inicio
            llamada.duracion_s = externa.duracion_s
            llamada.direccion = externa.direccion
            llamada.grabada = externa.grabada
            llamada.enlace_plataforma = externa.enlace_plataforma
            llamada.datos_origen = externa.datos_origen
            llamada.cliente_id = self._cliente(externa.telefono_cliente, externa.nombre_cliente)
            self._asignar_automatica(llamada)
            # Se agrega a la sesión recién completa: las consultas de arriba
            # harían un autoflush de una fila a medias.
            if nueva:
                self._sesion.add(llamada)
            resumen.nuevas += nueva
            resumen.actualizadas += not nueva
            resumen.sin_asignar += llamada.persona_id is None
        self._sesion.flush()
        return resumen

    def ultima_actividad_guardada(self, ids_externos: list[str]) -> dict[str, datetime | None]:
        """Para saber qué conversaciones cambiaron y necesitan sus mensajes."""
        return {
            id_externo: ultima
            for id_externo, ultima in self._sesion.execute(
                select(Conversacion.id_externo, Conversacion.ultima_actividad).where(
                    Conversacion.id_externo.in_(ids_externos)
                )
            )
        }

    def guardar_conversaciones(
        self, conversaciones: list[tuple[ConversacionExterna, list[dict] | None]]
    ) -> ResumenGuardado:
        """`mensajes` en None: la conversación no cambió y conserva su dirección
        y su cierre."""
        resumen = ResumenGuardado()
        existentes = self._existentes(
            Conversacion, [externa.id_externo for externa, _ in conversaciones]
        )
        for externa, mensajes in conversaciones:
            conversacion = existentes.get(externa.id_externo)
            nueva = conversacion is None
            if nueva:
                conversacion = Conversacion(
                    id_externo=externa.id_externo,
                    asignacion=ASIGNACION_AUTOMATICA,
                    direccion=INDETERMINADO,
                    cierre_aproximado=False,
                )
            cuenta = (
                self._cuentas.asegurar("chatwoot", externa.usuario) if externa.usuario else None
            )
            conversacion.cuenta_id = cuenta.id if cuenta else None
            conversacion.inicio = externa.inicio
            conversacion.ultima_actividad = externa.ultima_actividad
            conversacion.canal = externa.canal
            conversacion.estado = externa.estado
            conversacion.etiquetas = externa.etiquetas
            conversacion.datos_origen = externa.datos_origen
            conversacion.cliente_id = self._cliente(
                externa.telefono_cliente, externa.nombre_cliente
            )
            if mensajes is not None:
                conversacion.direccion = detectar_direccion(mensajes)
                cierre, aproximado = detectar_cierre(externa.datos_origen, mensajes)
                conversacion.cierre = cierre
                conversacion.cierre_aproximado = aproximado
            self._asignar_automatica(conversacion)
            if nueva:
                self._sesion.add(conversacion)
            resumen.nuevas += nueva
            resumen.actualizadas += not nueva
            resumen.sin_asignar += conversacion.persona_id is None
        self._sesion.flush()
        return resumen

    def _existentes(self, modelo, ids_externos: list[str]) -> dict:
        if not ids_externos:
            return {}
        return {
            fila.id_externo: fila
            for fila in self._sesion.scalars(
                select(modelo).where(modelo.id_externo.in_(ids_externos))
            )
        }

    def _cliente(self, telefono: str | None, nombre: str | None) -> int | None:
        normalizado = normalizar(telefono)
        if normalizado is None:
            return None
        cliente = self._sesion.scalar(select(Cliente).where(Cliente.telefono == normalizado.valor))
        if cliente is None:
            cliente = Cliente(
                telefono=normalizado.valor,
                telefono_original=normalizado.original,
                nombre=nombre,
                revisar=normalizado.revisar,
            )
            self._sesion.add(cliente)
            self._sesion.flush()
        elif nombre and not cliente.nombre:
            cliente.nombre = nombre
        return cliente.id

    # --- Asignación -----------------------------------------------------------

    def _resolver(self, interaccion) -> AsignacionResuelta:
        if interaccion.cuenta_id is None:
            return AsignacionResuelta(persona_id=None, motivo=MOTIVO_SIN_USUARIO, regla_id=None)
        return self.asignacion.resolver(interaccion.cuenta_id, interaccion.inicio)

    def _asignar_automatica(self, interaccion) -> bool:
        """Recalcula la asignación salvo que sea manual. Dice si cambió la persona."""
        if interaccion.asignacion == ASIGNACION_MANUAL:
            return False
        resuelta = self._resolver(interaccion)
        cambio = interaccion.persona_id != resuelta.persona_id
        interaccion.asignacion = ASIGNACION_AUTOMATICA
        interaccion.persona_id = resuelta.persona_id
        interaccion.regla_id = resuelta.regla_id
        interaccion.motivo_asignacion = resuelta.motivo
        return cambio

    def asignar_manual(self, tipo: Tipo, interaccion_id: int, persona_id: int | None) -> None:
        """Fija la persona a mano (o la deja sin asignar). La sincronización y
        los cambios de regla ya no la tocan."""
        interaccion = self._obtener(tipo, interaccion_id)
        if persona_id is not None:
            persona = self._personas.por_ids({persona_id}).get(persona_id)
            if persona is None or not persona.activa:
                raise ValueError("Elija un asesor activo.")
        interaccion.asignacion = ASIGNACION_MANUAL
        interaccion.persona_id = persona_id
        interaccion.regla_id = None
        interaccion.motivo_asignacion = MOTIVO_MANUAL
        self._sesion.flush()

    def volver_a_automatica(self, tipo: Tipo, interaccion_id: int) -> None:
        interaccion = self._obtener(tipo, interaccion_id)
        interaccion.asignacion = ASIGNACION_AUTOMATICA
        self._asignar_automatica(interaccion)
        self._sesion.flush()

    def _obtener(self, tipo: Tipo, interaccion_id: int):
        interaccion = self._sesion.get(MODELOS[tipo], interaccion_id)
        if interaccion is None:
            raise LookupError(f"No existe la {tipo} {interaccion_id}.")
        return interaccion

    def reasignar_cuenta(self, cuenta_id: int, desde: datetime) -> ResumenReasignacion:
        """Recalcula las interacciones automáticas de la cuenta desde esa fecha,
        por ejemplo después de guardar una regla nueva."""
        self.asignacion.olvidar(cuenta_id)
        resumen = ResumenReasignacion()
        conteo: dict[int | None, int] = {}
        for modelo in MODELOS.values():
            consulta = select(modelo).where(
                modelo.cuenta_id == cuenta_id,
                modelo.inicio >= desde,
                modelo.asignacion == ASIGNACION_AUTOMATICA,
            )
            for interaccion in self._sesion.scalars(consulta):
                resumen.revisadas += 1
                resumen.cambiaron += self._asignar_automatica(interaccion)
                conteo[interaccion.persona_id] = conteo.get(interaccion.persona_id, 0) + 1
        self._sesion.flush()

        nombres = {
            pid: p.etiqueta
            for pid, p in self._personas.por_ids({pid for pid in conteo if pid}).items()
        }
        resumen.por_persona = {
            (nombres.get(pid, "?") if pid is not None else SIN_ASIGNAR): cantidad
            for pid, cantidad in sorted(conteo.items(), key=lambda par: -par[1])
        }
        return resumen

    def simular_regla(
        self, cuenta_id: int, estrategia: str, parametros, vigente_desde: datetime
    ) -> ResumenReasignacion:
        """Qué pasaría con las interacciones si se guardara la regla, sin
        guardar nada. Lanza ReglaInvalida igual que crear_regla."""
        punto = self._sesion.begin_nested()
        try:
            self.asignacion.crear_regla(cuenta_id, estrategia, parametros, vigente_desde)
            return self.reasignar_cuenta(cuenta_id, vigente_desde)
        finally:
            punto.rollback()
            self.asignacion.olvidar(cuenta_id)
