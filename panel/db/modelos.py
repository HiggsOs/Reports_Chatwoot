"""Tablas de la base de datos.

Cada etapa del plan suma sus tablas aquí y una migración de Alembic que las
crea; nunca se edita una migración ya aplicada.
"""

from datetime import datetime
from typing import Any

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from panel.db.base import Base, MarcasDeTiempo
from panel.esquemas.personas import AREAS


class Persona(MarcasDeTiempo, Base):
    """Un asesor real. Reemplaza a `asesores.csv`.

    Las personas no se borran: quitarlas de la lista las desactiva, para que
    las llamadas, reglas y auditorías que las nombren sigan siendo válidas.
    """

    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(200))
    correo: Mapped[str] = mapped_column(String(320), unique=True)
    area: Mapped[str] = mapped_column(String(20))
    activa: Mapped[bool] = mapped_column(default=True, server_default=true())

    __table_args__ = (
        CheckConstraint(
            "area IN (" + ", ".join(f"'{area}'" for area in AREAS) + ")",
            name="area_valida",
        ),
        CheckConstraint("correo = lower(btrim(correo))", name="correo_normalizado"),
    )


PLATAFORMAS = ("cloudtalk", "chatwoot")


class Cuenta(MarcasDeTiempo, Base):
    """Una cuenta de una plataforma: un agente de CloudTalk o un usuario de
    Chatwoot. Puede ser de una persona o compartida; quién atendió lo decide su
    regla de asignación vigente.
    """

    __tablename__ = "cuentas"

    id: Mapped[int] = mapped_column(primary_key=True)
    plataforma: Mapped[str] = mapped_column(String(20))
    id_externo: Mapped[str] = mapped_column(String(64))
    nombre: Mapped[str] = mapped_column(String(200))
    correo: Mapped[str | None] = mapped_column(String(320))
    # La plataforma ya no la devuelve. Se conserva por su historia.
    activa: Mapped[bool] = mapped_column(default=True, server_default=true())

    reglas: Mapped[list["ReglaAsignacion"]] = relationship(
        back_populates="cuenta", order_by="ReglaAsignacion.vigente_desde"
    )

    __table_args__ = (
        UniqueConstraint("plataforma", "id_externo", name="uq_cuentas_plataforma_id_externo"),
        CheckConstraint(
            "plataforma IN (" + ", ".join(f"'{p}'" for p in PLATAFORMAS) + ")",
            name="plataforma_valida",
        ),
    )


class ReglaAsignacion(Base):
    """Qué estrategia reparte una cuenta, con qué parámetros y desde cuándo.

    Las reglas no se editan ni se borran: un cambio crea una regla nueva y
    cierra la anterior, así cada interacción se explica con la regla que regía
    en su fecha. Una regla corregida el mismo día queda con vigencia vacía
    (desde = hasta) y nunca rige.
    """

    __tablename__ = "reglas_asignacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id", ondelete="RESTRICT"))
    estrategia: Mapped[str] = mapped_column(String(50))
    # Validados con el modelo Pydantic de la estrategia al guardar y al leer.
    parametros: Mapped[dict[str, Any]] = mapped_column(JSONB)
    vigente_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    vigente_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    cuenta: Mapped[Cuenta] = relationship(back_populates="reglas")

    __table_args__ = (
        CheckConstraint(
            "vigente_hasta IS NULL OR vigente_hasta >= vigente_desde",
            name="vigencia_ordenada",
        ),
        # Una sola regla vigente por cuenta en cada momento.
        ExcludeConstraint(
            ("cuenta_id", "="),
            (func.tstzrange(vigente_desde, vigente_hasta, "[)"), "&&"),
            using="gist",
            name="ex_reglas_asignacion_vigencias_sin_superponer",
        ),
    )


class Cliente(MarcasDeTiempo, Base):
    """Un cliente, identificado por su teléfono normalizado. Une sus llamadas y
    sus conversaciones de Chatwoot."""

    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    # E.164 (+34612345678); si no se pudo interpretar, solo los dígitos.
    telefono: Mapped[str] = mapped_column(String(32), unique=True)
    telefono_original: Mapped[str] = mapped_column(String(64))
    nombre: Mapped[str | None] = mapped_column(String(200))
    revisar: Mapped[bool] = mapped_column(default=False, server_default=false())


ASIGNACION_AUTOMATICA = "automatica"
ASIGNACION_MANUAL = "manual"
ORIGENES_ASIGNACION = (ASIGNACION_AUTOMATICA, ASIGNACION_MANUAL)


class Asignable:
    """Quién atendió una interacción y por qué.

    `persona_id` vacío es «sin asignar». Una asignación `manual` la eligió el
    auditor y la sincronización nunca la pisa; una `automatica` sale de la
    regla de la cuenta y se recalcula si la regla cambia.
    """

    asignacion: Mapped[str] = mapped_column(
        String(20), default=ASIGNACION_AUTOMATICA, server_default=ASIGNACION_AUTOMATICA
    )
    motivo_asignacion: Mapped[str] = mapped_column(Text, default="", server_default="")

    @declared_attr
    def persona_id(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("personas.id", ondelete="RESTRICT"))

    @declared_attr
    def regla_id(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("reglas_asignacion.id", ondelete="RESTRICT"))

    @declared_attr
    def cliente_id(cls) -> Mapped[int | None]:
        return mapped_column(ForeignKey("clientes.id", ondelete="RESTRICT"))

    @classmethod
    def _restriccion_asignacion(cls) -> CheckConstraint:
        return CheckConstraint(
            "asignacion IN (" + ", ".join(f"'{o}'" for o in ORIGENES_ASIGNACION) + ")",
            name="asignacion_valida",
        )


AUDIO_GUARDADO = "guardado"  # en el almacén
AUDIO_PENDIENTE = "pendiente"  # en audios_pendientes, falta subirlo
AUDIO_SIN_GRABACION = "sin_grabacion"  # CloudTalk no tiene grabación
AUDIO_VENCIDO = "vencido"  # CloudTalk ya la borró
AUDIO_ELIMINADO = "eliminado"  # se borró del almacén al cumplir el plazo
ESTADOS_AUDIO = (AUDIO_GUARDADO, AUDIO_PENDIENTE, AUDIO_SIN_GRABACION, AUDIO_VENCIDO, AUDIO_ELIMINADO)

TRANSCRIPCION_HECHA = "transcrita"
TRANSCRIPCION_ELIMINADA = "eliminada"
ESTADOS_TRANSCRIPCION = (TRANSCRIPCION_HECHA, TRANSCRIPCION_ELIMINADA)


class Llamada(Asignable, MarcasDeTiempo, Base):
    """Una llamada contestada de CloudTalk."""

    __tablename__ = "llamadas"

    id: Mapped[int] = mapped_column(primary_key=True)
    id_externo: Mapped[str] = mapped_column(String(64), unique=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id", ondelete="RESTRICT"))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duracion_s: Mapped[int | None] = mapped_column(Integer)
    direccion: Mapped[str] = mapped_column(String(20))  # entrante, saliente, interna
    grabada: Mapped[bool] = mapped_column(default=False, server_default=false())
    # La página de la llamada en CloudTalk Analytics (`Cdr.recording_link`).
    enlace_plataforma: Mapped[str | None] = mapped_column(Text)
    # Lo que devolvió la API, tal cual, para no tener que volver a pedirlo si
    # después hace falta otro campo.
    datos_origen: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Audio (ver panel/audio/servicio.py). Vacío: nunca se pidió.
    audio_estado: Mapped[str | None] = mapped_column(String(20))
    audio_ruta: Mapped[str | None] = mapped_column(Text)  # relativa al almacén
    audio_canales: Mapped[int | None] = mapped_column(Integer)
    audio_bytes: Mapped[int | None] = mapped_column(Integer)
    audio_guardado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # «transcrita», o «eliminada» al cumplir el plazo. Vacío: sin transcribir.
    transcripcion_estado: Mapped[str | None] = mapped_column(String(20))

    cuenta: Mapped[Cuenta] = relationship()
    persona: Mapped[Persona | None] = relationship()
    cliente: Mapped[Cliente | None] = relationship()

    __table_args__ = (
        Asignable._restriccion_asignacion(),
        CheckConstraint(
            "audio_estado IS NULL OR audio_estado IN ("
            + ", ".join(f"'{e}'" for e in ESTADOS_AUDIO)
            + ")",
            name="audio_estado_valido",
        ),
        CheckConstraint(
            "transcripcion_estado IS NULL OR transcripcion_estado IN ("
            + ", ".join(f"'{e}'" for e in ESTADOS_TRANSCRIPCION)
            + ")",
            name="transcripcion_estado_valido",
        ),
        Index("ix_llamadas_inicio", "inicio"),
        Index("ix_llamadas_cuenta_id_inicio", "cuenta_id", "inicio"),
        Index("ix_llamadas_persona_id", "persona_id"),
        Index("ix_llamadas_cliente_id", "cliente_id"),
    )


class Conversacion(Asignable, MarcasDeTiempo, Base):
    """Una conversación de Chatwoot. La cuenta es el usuario asignado; sin
    usuario asignado queda sin cuenta y sin asignar."""

    __tablename__ = "conversaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    id_externo: Mapped[str] = mapped_column(String(64), unique=True)
    cuenta_id: Mapped[int | None] = mapped_column(ForeignKey("cuentas.id", ondelete="RESTRICT"))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ultima_actividad: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canal: Mapped[str] = mapped_column(String(200))  # nombre de la bandeja
    estado: Mapped[str] = mapped_column(String(20))
    etiquetas: Mapped[list[str]] = mapped_column(JSONB, default=list)
    direccion: Mapped[str] = mapped_column(String(20))  # Entrante, Saliente, Indeterminado
    cierre: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cierre_aproximado: Mapped[bool] = mapped_column(default=False, server_default=false())
    datos_origen: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Los mensajes tal como los devuelve Chatwoot, para leer el chat sin volver
    # a pedirlo. Vacío si la conversación no cambió desde que se guardó sin ellos.
    mensajes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    cuenta: Mapped[Cuenta | None] = relationship()
    persona: Mapped[Persona | None] = relationship()
    cliente: Mapped[Cliente | None] = relationship()

    __table_args__ = (
        Asignable._restriccion_asignacion(),
        Index("ix_conversaciones_inicio", "inicio"),
        Index("ix_conversaciones_cuenta_id_inicio", "cuenta_id", "inicio"),
        Index("ix_conversaciones_persona_id", "persona_id"),
        Index("ix_conversaciones_cliente_id", "cliente_id"),
    )


class PuntoSincronizacion(Base):
    """Hasta dónde llegó la sincronización de cada fuente, y cómo le fue."""

    __tablename__ = "puntos_sincronizacion"

    fuente: Mapped[str] = mapped_column(String(50), primary_key=True)
    hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_intento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_exito: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_error: Mapped[str | None] = mapped_column(Text)
    resumen: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AudioPendiente(Base):
    """Un MP3 escuchado que todavía no se pudo subir al almacén.

    Vive en la base y no en disco porque la app y la sincronización corren en
    contenedores distintos: así la sincronización puede reintentar la subida.
    """

    __tablename__ = "audios_pendientes"

    llamada_id: Mapped[int] = mapped_column(
        ForeignKey("llamadas.id", ondelete="CASCADE"), primary_key=True
    )
    contenido: Mapped[bytes] = mapped_column(LargeBinary)
    intentos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ultimo_error: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TranscripcionGuardada(Base):
    """Una transcripción de una llamada. Una llamada puede tener varias (por
    ejemplo, para comparar proveedores); una sola es la principal."""

    __tablename__ = "transcripciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    llamada_id: Mapped[int] = mapped_column(ForeignKey("llamadas.id", ondelete="CASCADE"))
    proveedor: Mapped[str] = mapped_column(String(50))
    modelo: Mapped[str] = mapped_column(String(100))
    idioma: Mapped[str] = mapped_column(String(10))
    # mono, estereo o estereo_duplicado: cómo era la grabación.
    canales_audio: Mapped[str] = mapped_column(String(20))
    # Lista de Segmento (panel/transcripcion/base.py) en JSON.
    segmentos: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    texto: Mapped[str] = mapped_column(Text)
    duracion_audio: Mapped[float | None] = mapped_column(Float)
    costo_estimado: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    principal: Mapped[bool] = mapped_column(default=False, server_default=false())
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_transcripciones_llamada_id", "llamada_id"),
        Index(
            "uq_transcripciones_una_principal",
            "llamada_id",
            unique=True,
            postgresql_where=text("principal"),
        ),
    )


TRABAJO_PENDIENTE = "pendiente"
TRABAJO_EN_PROCESO = "en_proceso"
TRABAJO_HECHO = "hecho"
TRABAJO_ERROR = "error"
ESTADOS_TRABAJO = (TRABAJO_PENDIENTE, TRABAJO_EN_PROCESO, TRABAJO_HECHO, TRABAJO_ERROR)


class TrabajoTranscripcion(MarcasDeTiempo, Base):
    """Un pedido de transcripción en la cola (patrón Command): lo crea el panel
    y lo procesa la sincronización."""

    __tablename__ = "trabajos_transcripcion"

    id: Mapped[int] = mapped_column(primary_key=True)
    llamada_id: Mapped[int] = mapped_column(ForeignKey("llamadas.id", ondelete="CASCADE"))
    proveedor: Mapped[str | None] = mapped_column(String(50))  # vacío: el de siempre
    estado: Mapped[str] = mapped_column(
        String(20), default=TRABAJO_PENDIENTE, server_default=TRABAJO_PENDIENTE
    )
    intentos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "estado IN (" + ", ".join(f"'{e}'" for e in ESTADOS_TRABAJO) + ")",
            name="estado_valido",
        ),
        Index("ix_trabajos_transcripcion_estado", "estado", "creado_en"),
        # Un solo pedido abierto por llamada.
        Index(
            "uq_trabajos_transcripcion_uno_abierto",
            "llamada_id",
            unique=True,
            postgresql_where=text("estado IN ('pendiente', 'en_proceso')"),
        ),
    )
