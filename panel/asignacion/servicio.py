"""Contexto de la asignación: lo que es común a todas las estrategias.

Busca la regla vigente de la cuenta en la fecha de la interacción, pasa la hora
a la zona de operación (España) y le pide la persona a la estrategia de esa
regla. También crea reglas nuevas, cerrando la anterior: las reglas nunca se
editan ni se borran.

La asignación manual de una interacción, que nunca se pisa, se guarda con la
interacción misma (llega con las llamadas y conversaciones, en la etapa 3).
"""

from collections.abc import Mapping
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from panel.asignacion import registro
from panel.asignacion.base import DIAS_SEMANA, EstrategiaAsignacion, ResultadoAsignacion
from panel.db.modelos import ReglaAsignacion
from panel.db.repositorios.cuentas import RepositorioCuentas, RepositorioReglas
from panel.db.repositorios.personas import RepositorioPersonas

ZONA_OPERACION_POR_DEFECTO = ZoneInfo("Europe/Madrid")

# «Desde siempre»: la primera regla de una cuenta suele valer también para las
# interacciones anteriores a su creación.
DESDE_SIEMPRE = datetime(2000, 1, 1, tzinfo=timezone.utc)

SIN_REGLA = "La cuenta no tiene regla de asignación"


class AsignacionResuelta(BaseModel):
    """El resultado de la estrategia, más la regla que lo produjo."""

    persona_id: int | None
    motivo: str
    regla_id: int | None


class ReglaInvalida(ValueError):
    """La regla no se puede guardar. `errores` trae los motivos, legibles."""

    def __init__(self, errores: list[str]) -> None:
        super().__init__("; ".join(errores))
        self.errores = errores


def _errores_de_validacion(error: ValidationError) -> list[str]:
    mensajes = []
    for detalle in error.errors():
        mensaje = str(detalle["msg"]).removeprefix("Value error, ")
        campo = ".".join(str(parte) for parte in detalle["loc"])
        mensajes.append(f"{campo}: {mensaje}" if campo else mensaje)
    return mensajes


class ServicioAsignacion:
    def __init__(self, sesion: Session, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO) -> None:
        self._sesion = sesion
        self._zona = zona
        self._cuentas = RepositorioCuentas(sesion)
        self._reglas = RepositorioReglas(sesion)
        self._personas = RepositorioPersonas(sesion)
        # Reglas por cuenta ya leídas, con sus parámetros validados: una
        # sincronización asigna miles de interacciones de pocas cuentas.
        self._cache: dict[int, list[tuple[ReglaAsignacion, EstrategiaAsignacion, BaseModel]]] = {}

    def asignar(self, cuenta_id: int, inicio: datetime) -> ResultadoAsignacion:
        """Qué persona atendió una interacción que empezó en `inicio`."""
        resuelta = self.resolver(cuenta_id, inicio)
        return ResultadoAsignacion(persona_id=resuelta.persona_id, motivo=resuelta.motivo)

    def resolver(self, cuenta_id: int, inicio: datetime) -> AsignacionResuelta:
        if inicio.tzinfo is None:
            raise ValueError("La hora de inicio debe traer zona horaria.")
        for regla, estrategia, parametros in self._reglas_de(cuenta_id):
            if regla.vigente_desde <= inicio and (
                regla.vigente_hasta is None or inicio < regla.vigente_hasta
            ):
                resultado = estrategia.asignar(inicio.astimezone(self._zona), parametros)
                return AsignacionResuelta(
                    persona_id=resultado.persona_id, motivo=resultado.motivo, regla_id=regla.id
                )
        return AsignacionResuelta(persona_id=None, motivo=SIN_REGLA, regla_id=None)

    def olvidar(self, cuenta_id: int) -> None:
        """Descarta las reglas en caché de la cuenta (por ejemplo, tras deshacer
        una simulación)."""
        self._cache.pop(cuenta_id, None)

    def _reglas_de(self, cuenta_id: int):
        if cuenta_id not in self._cache:
            reglas = []
            for regla in self._reglas.historial(cuenta_id):
                estrategia = registro.obtener(regla.estrategia)
                reglas.append(
                    (regla, estrategia, estrategia.Parametros.model_validate(regla.parametros))
                )
            self._cache[cuenta_id] = reglas
        return self._cache[cuenta_id]

    def crear_regla(
        self,
        cuenta_id: int,
        estrategia: str,
        parametros: Mapping | BaseModel,
        vigente_desde: datetime,
    ) -> ReglaAsignacion:
        """Guarda una regla nueva y cierra la anterior en `vigente_desde`.

        Si la anterior empezaba en el mismo momento, queda con vigencia vacía:
        es la forma de corregir una regla sin borrarla.
        """
        if vigente_desde.tzinfo is None:
            raise ValueError("vigente_desde debe traer zona horaria.")
        if self._cuentas.obtener(cuenta_id) is None:
            raise ReglaInvalida([f"No existe la cuenta {cuenta_id}."])

        try:
            implementacion = registro.obtener(estrategia)
        except registro.EstrategiaDesconocida as error:
            raise ReglaInvalida([str(error)]) from None
        if implementacion.retirada:
            raise ReglaInvalida(
                [f"La estrategia «{implementacion.titulo}» está retirada: no admite reglas nuevas."]
            )

        if isinstance(parametros, BaseModel):
            parametros = parametros.model_dump(mode="json")
        try:
            validados = implementacion.Parametros.model_validate(parametros)
        except ValidationError as error:
            raise ReglaInvalida(_errores_de_validacion(error)) from None

        errores = self._errores_de_personas(implementacion, validados)
        anterior = self._reglas.ultima(cuenta_id)
        if anterior is not None:
            if vigente_desde < anterior.vigente_desde:
                errores.append(
                    "La regla nueva no puede empezar antes que la última regla de la "
                    f"cuenta ({self.formatear_fecha(anterior.vigente_desde)})."
                )
            elif anterior.vigente_hasta is not None and vigente_desde < anterior.vigente_hasta:
                errores.append("La regla nueva se superpone con la última regla de la cuenta.")
        if errores:
            raise ReglaInvalida(errores)

        if anterior is not None and anterior.vigente_hasta is None:
            anterior.vigente_hasta = vigente_desde
            self._sesion.flush()

        self._cache.pop(cuenta_id, None)
        return self._reglas.agregar(
            ReglaAsignacion(
                cuenta_id=cuenta_id,
                estrategia=implementacion.nombre,
                parametros=validados.model_dump(mode="json"),
                vigente_desde=vigente_desde,
                vigente_hasta=None,
            )
        )

    def _errores_de_personas(self, estrategia: EstrategiaAsignacion, parametros) -> list[str]:
        ids = estrategia.personas(parametros)
        encontradas = self._personas.por_ids(ids)
        errores = [f"No existe la persona {pid}." for pid in sorted(ids - encontradas.keys())]
        errores += [
            f"{persona.etiqueta} no está activa en la lista de asesores."
            for persona in encontradas.values()
            if not persona.activa
        ]
        return errores

    def describir(self, regla: ReglaAsignacion) -> list[str]:
        estrategia = registro.obtener(regla.estrategia)
        parametros = estrategia.Parametros.model_validate(regla.parametros)
        ids = estrategia.personas(parametros)
        nombres = {pid: p.etiqueta for pid, p in self._personas.por_ids(ids).items()}
        return estrategia.describir(parametros, nombres)

    def personas_inactivas(self, regla: ReglaAsignacion) -> list[str]:
        """Personas que nombra la regla y ya no están activas."""
        estrategia = registro.obtener(regla.estrategia)
        ids = estrategia.personas(estrategia.Parametros.model_validate(regla.parametros))
        return sorted(p.etiqueta for p in self._personas.por_ids(ids).values() if not p.activa)

    def formatear_fecha(self, momento: datetime) -> str:
        if momento <= DESDE_SIEMPRE:
            return "siempre"
        return momento.astimezone(self._zona).strftime("%d/%m/%Y %H:%M")

    def inicio_del_dia(self, dia) -> datetime:
        """Medianoche de ese día en la zona de operación."""
        return datetime.combine(dia, time.min, tzinfo=self._zona)


class CeldaSemanal(BaseModel):
    dia: int
    hora: time
    resultado: ResultadoAsignacion


def ocupacion_semanal(
    estrategia: EstrategiaAsignacion, parametros, paso_minutos: int = 30
) -> list[CeldaSemanal]:
    """Quién queda asignado en cada tramo de una semana tipo.

    Sirve para dibujar el horario de cualquier estrategia sin que la pantalla
    sepa cómo funciona cada una: solo le pregunta a la estrategia, tramo por
    tramo. Las horas son locales, así que el horario de verano no influye.
    """
    lunes = datetime(2026, 1, 5, tzinfo=ZONA_OPERACION_POR_DEFECTO)  # un lunes cualquiera
    celdas = []
    for dia in range(len(DIAS_SEMANA)):
        momento = lunes + timedelta(days=dia)
        while momento.day == (lunes + timedelta(days=dia)).day:
            celdas.append(
                CeldaSemanal(
                    dia=dia,
                    hora=momento.time(),
                    resultado=estrategia.asignar(momento, parametros),
                )
            )
            momento += timedelta(minutes=paso_minutos)
    return celdas
