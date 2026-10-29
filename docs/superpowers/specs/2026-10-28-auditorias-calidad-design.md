# Panel de auditorías de calidad — Plan general

Fecha: 2026-10-28
Estado: propuesto

Los patrones de diseño de cada parte están en
`2026-10-29-patrones-de-diseno.md`.

## 1. Problema

Hoy la aplicación genera CSV a pedido contra las APIs de Chatwoot, Ringover y
CloudTalk. El panel nuevo usa solo Chatwoot y CloudTalk. No guarda nada salvo `asesores.csv` y una caché de archivos, así que
no permite:

- Escuchar una llamada desde el panel.
- Saber qué persona atendió una llamada cuando la cuenta del asesor es
  compartida: varias personas usan la misma cuenta, cada una en una o dos
  franjas horarias.
- Ver todo lo que pasó con un cliente (chats y llamadas) a partir de su número.
- Calificar la calidad de cada asesor y descargar un reporte de esas
  auditorías.

## 2. Alcance

**Incluye:**

- Base de datos PostgreSQL con personas, cuentas, reglas de asignación,
  clientes, llamadas, conversaciones y auditorías.
- Sincronización periódica de CloudTalk y Chatwoot hacia la base.
- Asignación de cada llamada y conversación a la persona real, con estrategias
  intercambiables por cuenta. La primera: un asesor tiene horario fijo y todo lo
  que cae fuera es del otro.
- Traza por número de teléfono del cliente.
- Escucha de grabaciones bajo demanda, con guardado en MP3 en el FTP de las
  llamadas escuchadas.
- Transcripción propia de las llamadas (hoy ninguna trae transcripción), con
  proveedores intercambiables: OpenAI, Alibaba y otros.
- Fichas de auditoría configurables, pantalla de auditoría y reporte
  descargable.
- Un único usuario administrador, como hoy.

**No incluye (por ahora):**

- **Ringover.** El panel nuevo trabaja solo con CloudTalk. La pestaña de
  Ringover que existe hoy no se toca mientras dure la transición; se retira
  cuando se decida.
- **Usuarios con roles.** Todo se maneja con el usuario administrador.
- Puntuar de forma automática con IA, enviar reportes por correo, o que los
  asesores entren a ver su propia nota.

La arquitectura no impide agregar nada de esto después.

## 3. Decisiones tomadas

| Decisión | Elección | Motivo |
|---|---|---|
| Base de datos | PostgreSQL | El panel y el proceso `sync` escriben a la vez; EasyPanel lo levanta como servicio |
| Plataforma de llamadas | Solo CloudTalk | Ringover no se usa en el panel nuevo |
| Asignación en Chatwoot | Por el usuario de Chatwoot asignado a la conversación | Todas las bandejas son compartidas, así que la bandeja no dice quién atendió |
| Usuarios del panel | Un solo administrador (el login actual) | No se necesitan roles por ahora |
| ORM | SQLAlchemy 2.x (estilo tipado `Mapped[...]`) | Estándar en Python; separa el modelo de la consulta |
| Migraciones | Alembic | Acompaña a SQLAlchemy; el esquema evoluciona sin perder datos |
| Validación y tipos | Pydantic v2 | Esquemas de entrada y salida, y la configuración (`Config` es un modelo Pydantic inmutable que se arma desde las variables de entorno) |
| Interfaz | Streamlit (se mantiene) | Se reutiliza lo existente; alcanza para un equipo interno |
| CSV | Solo como **descarga**; nada se guarda en CSV | `asesores.csv` se migra a la base una vez y deja de usarse |
| Zona horaria de las franjas | `Europe/Madrid` | Los turnos se definen en hora de España |
| Cuentas compartidas | Patrón **Strategy**: cada cuenta tiene una regla con su estrategia de asignación | Hay distintas formas de repartir una cuenta; la primera es «uno fijo y el resto al otro» |
| Almacenamiento de fechas | `timestamptz` en UTC | La zona se aplica solo al mostrar o al evaluar franjas |
| País por defecto de los teléfonos | España (`+34`) | La mayoría de las llamadas son en España |
| Normalización de teléfonos | Librería `phonenumbers`, formato E.164 | Evita reglas a mano por país |
| Audio | Mixto: bajo demanda; se guarda en MP3 lo que se escucha | Poco espacio y la evidencia de cada auditoría queda guardada |
| Retención de audios | 3 meses desde la fecha de la llamada | Alcanza para auditar y reclamar una nota |
| Retención de transcripciones | 3 años desde la fecha de la llamada | Plazo definido por la empresa; las auditorías se conservan |
| Almacén de audio | Hosting contratado (Plesk) por **SFTP** en el puerto 8023 | Ya está pago por un año; SFTP usa un solo puerto cifrado y evita los problemas de FTPS con conexiones pasivas y reutilización de sesión TLS |
| Acceso al almacén | Interfaz `AlmacenAudio` con implementaciones `sftp` y `local` (FTPS o S3 se suman como otra implementación si hacen falta) | Cambiar de servidor al vencer el año (u otro destino, como S3) es cambiar la configuración |
| Rutas de audio | Relativas al directorio del FTP | Permite cambiar de servidor sin tocar la base |
| Transcripción | Propia, con el patrón **Strategy**: una estrategia por proveedor | Ninguna llamada trae transcripción; se puede cambiar o comparar proveedores sin tocar el resto del código |
| Proveedor inicial | OpenAI; Alibaba y otros quedan como estrategias posteriores | Elegido por la empresa |
| Mono o estéreo | Se detecta en cada WAV; no se supone | CloudTalk solo garantiza WAV |
| Cuándo transcribir | Bajo demanda al abrir una llamada, y en lote por filtros con costo estimado previo | Coherente con la estrategia mixta de audio; no se paga por llamadas que nadie audita |

## 4. Arquitectura

```
┌──────────────────────── Frontend ─────────────────────────┐
│ Streamlit multipágina (st.navigation)                      │
│ login · asesores · franjas · historial · auditoría · ...   │
└───────────────┬────────────────────────────────────────────┘
                │ solo llama a servicios (nunca SQL directo)
┌───────────────┴──────────────── Backend ──────────────────┐
│ servicios/   lógica de negocio, recibe y devuelve Pydantic │
│ db/          modelos SQLAlchemy, sesión, Alembic           │
│ clientes/    chatwoot.py, cloudtalk.py                     │
│ audio/       conversión a MP3 y almacén (SFTP/local)       │
│ transcripcion/ estrategias por proveedor (OpenAI, Alibaba…)│
│ sync/        proceso aparte que llena la base y transcribe │
└───────┬───────────────────┬───────────────────┬────────────┘
        │                   │                   │
   PostgreSQL          Servidor FTP     APIs de transcripción
```

Se despliegan **tres servicios en EasyPanel** con la misma imagen Docker:

1. `app`: Streamlit (como hoy).
2. `sync`: el mismo código con otro comando (`python -m sync`), que corre la
   sincronización cada cierto tiempo.
3. `postgres`: el servicio de base de datos de EasyPanel.

El núcleo no importa Streamlit, igual que hoy: el frontend se puede cambiar
después (por ejemplo a FastAPI + React) sin reescribir el backend.

## 5. Backend

### 5.1 Estructura de carpetas

```
panel/                 # se llama panel/ y no app/ para no chocar con app.py
  composicion.py       # raíz de composición: arma las piezas concretas
  db/
    base.py            # engine, SessionLocal, Base
    modelos.py         # tablas SQLAlchemy
    migraciones/       # Alembic
    repositorios/      # un repositorio por agregado
  esquemas/            # modelos Pydantic de entrada/salida
  clientes/            # chatwoot.py, cloudtalk.py (los actuales)
  fuentes/             # adaptadores FuenteLlamadas / FuenteConversaciones
  servicios/
    personas.py        # personas y cuentas
    telefonos.py       # normalización
    clientes.py        # historial por número
    audio.py           # flujo de escucha y guardado
    auditorias.py      # fichas, auditorías, puntajes
    reportes.py        # armado de reportes y exportación
    retencion.py       # borrado de audios (3 meses) y transcripciones (3 años)
  audio/
    conversion.py      # WAV → MP3 con ffmpeg
    almacen.py         # AlmacenAudio y sus implementaciones: local y SFTP (paramiko)
    huella.py          # python -m panel.audio.huella: huella del servidor SFTP
    servicio.py        # escuchar, subir pendientes y retención
  asignacion/
    base.py            # interfaz EstrategiaAsignacion y esquemas
    registro.py        # nombre → estrategia
    servicio.py        # contexto: regla vigente, manual, reasignación
    estrategias/
      dueno_unico.py
      fijo_y_resto.py
      franjas_completas.py
  transcripcion/
    base.py            # interfaz EstrategiaTranscripcion y esquemas
    registro.py        # nombre → estrategia; elige según configuración
    servicio.py        # contexto: prepara audio, llama, normaliza, guarda
    estrategias/
      openai.py
      alibaba.py
      falsa.py         # para pruebas y desarrollo, sin costo
  sync/
    __main__.py        # bucle del proceso de sincronización
    cloudtalk.py
    chatwoot.py
  ui/                  # frontend (sección 6)
tests/
```

Los módulos actuales de Chatwoot y CloudTalk (`chatwoot.py`, `cloudtalk.py`,
`reporte.py`, `reporte_cloudtalk.py`) se mueven a `clientes/` y `servicios/`
sin cambiar su lógica, y sus pruebas se conservan. `ringover.py` y
`reporte_ringover.py` quedan donde están, solo para la pestaña actual.

### 5.2 Modelo de datos

```
cuentas ── reglas_asignacion (estrategia + parámetros, con vigencia)
   │               │ nombra personas
   │            personas
   │               │ persona asignada
   ├── llamadas ───┼──── transcripciones
   │               │
   └── conversaciones
           │
clientes ──┘ (por teléfono, también ligado a llamadas)

fichas ── criterios
   │          │
auditorias ── puntajes      (auditoría → llamada o conversación,
                              y persona auditada)
```

| Tabla | Campos principales | Notas |
|---|---|---|
| `personas` | id, nombre, correo, área (`Comercial`/`RDC`), activa | El asesor real; reemplaza a `asesores.csv` |
| `cuentas` | id, plataforma (`cloudtalk`/`chatwoot`), id_externo, nombre, correo | Se crean solas desde `sync`. En CloudTalk, el agente; en Chatwoot, el usuario (agente) |
| `reglas_asignacion` | id, cuenta_id, estrategia (`dueno_unico`/`fijo_y_resto`/`franjas_completas`…), parámetros (JSONB), vigente_desde, vigente_hasta | Parámetros validados con el modelo Pydantic de la estrategia; horas en `Europe/Madrid`. Una sola regla vigente por cuenta a la vez (restricción `EXCLUDE` de Postgres). Sección 5.3 |
| `clientes` | id, teléfono_e164, teléfono_original, nombre, revisar | `revisar` marca números que no se pudieron normalizar |
| `llamadas` | id, plataforma, id_externo, cuenta_id, cliente_id, persona_id, asignación (`automática`/`manual`/`sin_asignar`), regla_id, motivo_asignación, inicio, duración, dirección, estado, enlace_plataforma, audio_estado, audio_ruta, canales_audio, transcripción_principal_id, transcripcion_estado | Único por (plataforma, id_externo) |
| `transcripciones` | id, llamada_id, proveedor, modelo, idioma, segmentos (JSONB), texto, duración_audio, costo_estimado, creado_en | Una llamada puede tener varias (por ejemplo, para comparar proveedores); una es la principal. Se borran a los 3 años (sección 5.6) |
| `trabajos_transcripcion` | id, llamada_id, proveedor, estado (`pendiente`/`en_proceso`/`hecho`/`error`), intentos, error, pedido_por | Cola que procesa `sync` (sección 5.7) |
| `conversaciones` | id, id_externo, inbox (solo informativo), cuenta_id (el usuario asignado), cliente_id, persona_id, asignación, regla_id, motivo_asignación, inicio, cierre, estado, etiquetas, dirección, área | Los mensajes se guardan aparte o en JSONB |
| `fichas` | id, nombre, versión, activa | Las fichas se versionan: una auditoría vieja conserva su ficha |
| `criterios` | id, ficha_id, nombre, descripción, peso, puntaje_máx, crítico | Un criterio crítico en cero anula la nota |
| `auditorias` | id, ficha_id, llamada_id o conversación_id, persona_id, fecha, nota_final, comentario, estado (`borrador`/`cerrada`) | `persona_id` se copia al cerrar: si luego se reasigna la llamada, la auditoría no cambia |
| `puntajes` | auditoría_id, criterio_id, puntaje, comentario | |

Todas las tablas llevan `creado_en` y `actualizado_en`.

### 5.3 Asignación a la persona real (patrón Strategy)

Cada cuenta tiene una **regla de asignación**: qué estrategia usa para decidir
quién atendió cada llamada o conversación, y con qué parámetros. Como en la
transcripción, todas las estrategias implementan la misma interfaz, así que
sumar una forma nueva de repartir no toca el resto del código.

```
              ServicioAsignacion (contexto)
              respeta lo manual · busca la regla vigente · guarda
                              │ usa
              «interfaz» EstrategiaAsignacion
              asignar(interaccion, regla) -> ResultadoAsignacion
       ┌──────────────┬───────────────────┬──────────────────┐
  DuenoUnico     FijoYResto          FranjasCompletas     (futuras)
```

**Interfaz** (`asignacion/base.py`):

```python
class InteraccionAAsignar(BaseModel):
    cuenta_id: int
    inicio: datetime                 # UTC
    tipo: Literal["llamada", "conversacion"]

class ResultadoAsignacion(BaseModel):
    persona_id: int | None           # None = sin asignar
    motivo: str                      # se muestra al auditor

class EstrategiaAsignacion(Protocol, Generic[P]):
    nombre: str
    Parametros: type[P]              # modelo Pydantic propio de la estrategia
    def asignar(self, interaccion: InteraccionAAsignar,
                parametros: P) -> ResultadoAsignacion: ...
    def validar(self, parametros: P) -> list[str]: ...  # problemas a mostrar
```

Cada estrategia define sus parámetros como un modelo Pydantic. Se guardan en
la base como JSONB y se validan con ese modelo al leerlos y al guardarlos, así
que una regla mal cargada no llega a usarse.

**Estrategias:**

| Estrategia | Parámetros | Cómo asigna |
|---|---|---|
| `dueno_unico` | `persona_id` | Todo a esa persona. Es la de las cuentas que no son compartidas |
| `fijo_y_resto` ⭐ primera | `persona_fija_id`, `franjas_fijas` (día, inicio, fin), `persona_resto_id` | Si la hora cae dentro del horario de la persona fija, es de ella; **todo lo que cae fuera es de la otra persona**. Nunca deja nada sin asignar |
| `franjas_completas` | lista de (persona, día, inicio, fin) | Cada persona tiene sus franjas; lo que no cae en ninguna queda sin asignar. Para cuando los dos horarios son fijos |

**Chatwoot.** Todas las bandejas son compartidas, así que la bandeja no sirve
para separar. La cuenta es el **usuario de Chatwoot asignado a la
conversación**, y cada una usa `dueno_unico` hacia su persona. Cuando `sync`
encuentra un usuario nuevo de Chatwoot cuyo correo coincide con el de una
persona, crea esa regla solo; si no coincide, la cuenta queda sin regla y sus
conversaciones van a *Sin asignar*. Una conversación sin usuario asignado
también queda *Sin asignar*. Si en el futuro un usuario de Chatwoot se
comparte entre dos personas, se le asigna `fijo_y_resto` como a una cuenta de
CloudTalk.

Más adelante se pueden sumar otras, por ejemplo una que lea los turnos desde un
Excel o desde un sistema de turnos, o una que use el agente que registra la
plataforma cuando esté disponible.

Ejemplo de `fijo_y_resto` para una cuenta que usan Juan (fijo) y Ana:

```json
{
  "persona_fija_id": 12,
  "franjas_fijas": [
    {"dias": [0, 1, 2, 3, 4], "inicio": "08:00", "fin": "14:00"},
    {"dias": [0, 1, 2, 3, 4], "inicio": "16:00", "fin": "19:00"}
  ],
  "persona_resto_id": 15
}
```

Una llamada del martes a las 10:30 (hora de España) es de Juan; una del
martes a las 15:00, del sábado o de las 20:00 es de Ana. El motivo queda
guardado: «Fuera del horario fijo de Juan → Ana».

**Contexto** (`asignacion/servicio.py`), común a todas las estrategias:

1. Si la interacción tiene una asignación `manual`, no la toca nunca.
2. Busca la regla de la cuenta **vigente en la fecha de la interacción**
   (`reglas_asignacion` tiene vigencia), así que un cambio de turnos no altera
   las llamadas anteriores.
3. Convierte la hora de UTC a `Europe/Madrid` antes de pasarla a la
   estrategia; las estrategias no saben de zonas horarias.
4. Pide la estrategia al registro según `regla.estrategia`, valida los
   parámetros, asigna y guarda la persona, la regla usada y el motivo.
5. Si una cuenta no tiene regla, la interacción queda sin asignar y aparece en
   la bandeja.

**Reasignación.** Cuando se crea o edita una regla, se recalculan las
interacciones de esa cuenta en su vigencia, salvo las manuales. Antes de
guardar, el panel muestra una vista previa: «De las 340 llamadas del
período, 210 quedan para Juan y 130 para Ana; cambian de dueño 12». La
reasignación y la vista previa llegaron en la etapa 3, con las llamadas y
conversaciones.

**Pruebas** (funciones puras, sin base de datos), para cada estrategia:
dentro y fuera de cada franja, el corte entre dos franjas de la misma persona,
los bordes exactos (inicio incluido, fin excluido), fines de semana, el cambio
de vigencia de la regla y los dos cambios de horario de verano en España. Las
franjas no cruzan la medianoche; un turno así se carga como dos franjas.

### 5.4 Teléfonos

`normalizar(texto) -> (e164 | None, revisar: bool)` con `phonenumbers` y
región `ES` por defecto. Si el número trae código de país, se respeta. Si no
se puede interpretar, se guardan solo los dígitos y se marca `revisar`.

Origen del teléfono del cliente:

- CloudTalk: `Contact.contact_numbers` del historial de llamadas.
- Chatwoot: `meta.sender.phone_number` de la conversación.

### 5.5 Sincronización (`sync`)

Proceso aparte que corre cada N minutos (`SYNC_INTERVALO_MINUTOS`):

- Cada plataforma guarda su último punto sincronizado; cada ciclo trae solo
  lo nuevo, con un margen de solapamiento para no perder registros tardíos.
- Escribe con *upsert* por (plataforma, id_externo): repetir un ciclo no
  duplica nada.
- CloudTalk: historial de llamadas (con `recording_link` para saber cuáles
  tienen grabación). Respeta el límite de 60 peticiones por minuto, como hoy.
- Procesa la cola de transcripciones (sección 5.7).
- Chatwoot: conversaciones con el usuario asignado, inbox, etiquetas y
  teléfono. Se crea o actualiza la cuenta de cada usuario de Chatwoot.
- Después de guardar, aplica la asignación (5.3) y la traza por teléfono (5.4).
- Un bloqueo en Postgres (`pg_advisory_lock`) impide que corran dos ciclos a
  la vez.
- Hay una tarea aparte para cargar datos históricos de un rango a elección.
- Una vez al día aplica la retención (sección 5.6).

La caché de archivos actual (`DATA_DIR/cache`) deja de ser necesaria.

### 5.6 Audio

Flujo `obtener_audio(llamada) -> bytes`:

1. Si `audio_ruta` existe, se baja el MP3 del FTP.
2. Si no, se pide el WAV a la plataforma
   (CloudTalk: `GET /calls/recording/{id}.json`). `404` → `sin_grabación`;
   `410` → `vencida`. En ninguno de los dos casos se reintenta.
3. Se convierte a MP3 con `ffmpeg` y se devuelve para reproducirlo: mono a
   32 kbps, o estéreo a 64 kbps si la grabación es estéreo, para no perder la
   separación de canales que usa la transcripción (etapa 6). Con audio
   telefónico de 8 kHz el MP3 ocupa unas cuatro veces menos que el WAV.
4. La subida al FTP corre después de mostrar el reproductor. Si falla, el MP3
   queda en la tabla `audios_pendientes` (en la base y no en disco, porque la
   app y `sync` son contenedores distintos) y `sync` reintenta la subida.

Ruta en el FTP: `{plataforma}/{año}/{mes}/{id_externo}.mp3`, guardada en la
base relativa a `FTP_DIR`.

El servidor es el hosting contratado, administrado con Plesk. Se usa **SFTP**
(opción «Permitir SFTP para cuentas FTP», puerto 8023) con una cuenta FTP
propia cuyo directorio está fuera de la carpeta pública del sitio. El FTP sin
cifrar no se usa. FTPS no se implementó: se suma como otra implementación de
`AlmacenAudio` si algún día hace falta.

**Retención de audios: 3 meses** (`AUDIO_RETENCION_DIAS=90`), contados desde
la fecha de la llamada. Una vez al día, `sync` borra del FTP los MP3 vencidos y marca
la llamada como `audio_estado = eliminado`. Lo que se conserva
en la base después de ese plazo:

- La transcripción (hasta cumplir 3 años), las auditorías con sus puntajes y
  comentarios, y los datos de la llamada: el reporte histórico no pierde nada.
- No se borra un audio con una auditoría en `borrador`; se borra cuando la
  auditoría se cierra, si ya pasó el plazo.

Si alguien abre una llamada vencida, el panel intenta traer el audio otra vez
desde la plataforma por si aún la conserva; si responde `404` o `410`, avisa
que el audio ya no está disponible y muestra solo la transcripción. Ese
audio traído de nuevo no se vuelve a guardar en el FTP.

El borrado se prueba con fechas fijas: el día 90 se conserva, el 91 se borra.
Antes de borrar, `sync` registra en el log cuántos archivos y cuántos MB va a
liberar.

`enlace_plataforma` (`Cdr.recording_link` en CloudTalk) se guarda para el
botón «Abrir en CloudTalk». Solo se pide audio a CloudTalk cuando ese enlace
existe, para no gastar peticiones en llamadas sin grabación.

**Retención de transcripciones: 3 años** (`TRANSCRIPCION_RETENCION_DIAS=1095`),
contados desde la fecha de la llamada. La misma tarea diaria borra las filas de
`transcripciones` vencidas (texto y segmentos) y marca la llamada como
`transcripcion_estado = eliminada_por_retencion`. Las auditorías no se
borran: su nota, sus puntajes y sus comentarios siguen en los reportes. La
llamada vencida no se vuelve a transcribir sola; el botón «Transcribir» queda
desactivado si ya no hay audio en ninguna parte.

Las pruebas de retención usan fechas fijas en los dos bordes: día 90 / 91
para los audios y día 1095 / 1096 para las transcripciones.

### 5.7 Transcripción (patrón Strategy)

Ninguna llamada trae transcripción de la plataforma, así que se transcribe con
un proveedor externo. Cada proveedor es una **estrategia** con la misma
interfaz; el resto del sistema solo conoce esa interfaz.

```
                 ServicioTranscripcion (contexto)
                 prepara audio · elige estrategia · guarda
                              │ usa
                 «interfaz» EstrategiaTranscripcion
                 transcribir(audio, opciones) -> Transcripcion
           ┌──────────────┬──────────────┬──────────────┐
     EstrategiaOpenAI  EstrategiaAlibaba  EstrategiaX   EstrategiaFalsa
```

**Interfaz** (`transcripcion/base.py`):

```python
class OpcionesTranscripcion(BaseModel):
    idioma: str = "es"
    hablantes: int = 2
    vocabulario: list[str] = []      # nombres de productos, marcas

class Segmento(BaseModel):
    hablante: Literal["agente", "cliente", "desconocido"]
    inicio: float                    # segundos
    fin: float
    texto: str

class Transcripcion(BaseModel):
    proveedor: str
    modelo: str
    idioma: str
    segmentos: list[Segmento]
    duracion_audio: float
    costo_estimado: Decimal | None

class Capacidades(BaseModel):
    diarizacion: bool                # separa hablantes por sí mismo
    tamano_max_mb: float | None      # límite por archivo
    duracion_max_s: float | None
    requiere_url: bool               # pide una URL en vez del archivo

class EstrategiaTranscripcion(Protocol):
    nombre: str
    capacidades: Capacidades
    def transcribir(self, audio: AudioPreparado,
                    opciones: OpcionesTranscripcion) -> Transcripcion: ...
    def costo_estimado(self, duracion_s: float) -> Decimal | None: ...
```

Cada estrategia traduce la respuesta propia del proveedor a esta forma común.
Las pantallas, la base y los reportes nunca ven el formato de un proveedor.

**Registro** (`transcripcion/registro.py`): un diccionario nombre → clase.
Agregar un proveedor es escribir una clase nueva y registrarla; nada más
cambia. El proveedor por defecto sale de `TRANSCRIPCION_PROVEEDOR`, y en cada
pedido se puede elegir otro. Se puede definir una cadena de respaldo
(`TRANSCRIPCION_RESPALDO`): si el principal falla, se prueba con el siguiente.

**Contexto** (`transcripcion/servicio.py`) hace lo que es común a todos:

1. Obtiene el audio con el flujo de la sección 5.6, así que transcribir una
   llamada también la deja guardada en el FTP.
2. **Detecta los canales de cada WAV y elige el camino.** De CloudTalk solo se
   sabe que entrega WAV, no si es mono o estéreo, así que se decide por
   archivo y no por configuración (ver «Mono o estéreo» más abajo).
3. Ajusta el audio a las `capacidades` de la estrategia: lo parte en trozos si
   supera el tamaño o la duración máximos y une los segmentos al final; si la
   estrategia `requiere_url`, publica el archivo en una URL temporal.
4. Llama a la estrategia, guarda el resultado en `transcripciones` y la marca
   como principal si la llamada no tenía otra.

**Mono o estéreo.** Antes de transcribir, el contexto lee la cabecera del WAV
(con `ffprobe`, sin costo ni llamadas externas) y sigue uno de dos caminos:

| Caso | Cómo se detecta | Qué se hace | Quién es el agente |
|---|---|---|---|
| **Estéreo real** | 2 canales con contenido distinto | Se separa cada canal y se transcribe por separado; se intercalan los segmentos por su marca de tiempo | Exacto: cada canal es una persona. Qué canal es el agente se configura (`CLOUDTALK_CANAL_AGENTE`) tras escuchar una grabación |
| **Mono**, o estéreo con los dos canales iguales | 1 canal, o 2 canales casi idénticos (se comparan) | Se transcribe el audio completo con un modelo que separa hablantes (diarización) | El modelo devuelve hablantes `A`, `B`…; se deduce cuál es el agente y, si no se puede, queda `desconocido` y el auditor lo corrige con un clic |

Los dos caminos imponen requisitos distintos al modelo, y el contexto solo usa
una estrategia que los cumpla según sus `capacidades`:

- Estéreo: necesita **marcas de tiempo** por segmento, para intercalar los dos
  canales en orden. Sin ellas, el diálogo quedaría con todo el agente primero
  y todo el cliente después.
- Mono: necesita **diarización**.

Para mejorar el caso mono, OpenAI acepta muestras de voz de hablantes
conocidos (hasta 4, de 2 a 10 segundos cada una). Como el sistema sabe qué
persona tenía asignada la llamada, se puede guardar una muestra corta de la voz
de cada asesor y enviarla como «agente», así el modelo marca directamente sus
intervenciones. Queda como mejora opcional, después de ver los resultados sin
muestra.

Se guarda en la llamada qué camino se usó (`canales_audio`: `mono`,
`estereo`, `estereo_duplicado`), para medir después la calidad de cada uno.

**Estrategias iniciales.** Los nombres de modelos y los precios cambian
seguido, así que el modelo de cada proveedor es configurable
(`OPENAI_MODELO_TRANSCRIPCION`, `ALIBABA_MODELO_TRANSCRIPCION`) y se confirma
contra la documentación vigente al implementar:

| Estrategia | Opciones de modelo | A tener en cuenta |
|---|---|---|
| `openai` ⭐ proveedor inicial | `gpt-transcribe` (el actual), `gpt-4o-transcribe-diarize` (separa hablantes), `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, `whisper-1` | Límite de 25 MB por archivo (el MP3 ayuda; si no, se parte). **Todos menos `gpt-transcribe` están anunciados para apagarse el 2027-02-26.** Cada modelo devuelve un formato distinto (`diarized_json` con hablantes y tiempos, `verbose_json` con tiempos, `json` solo con texto), y la estrategia lo traduce a la forma común |
| `alibaba` | Model Studio / DashScope: Paraformer, SenseVoice, Qwen-ASR | La transcripción de archivos grabados de Paraformer es asíncrona y pide una URL pública del audio; hay que elegir la región internacional |
| `falsa` | — | Devuelve un texto fijo; para pruebas y desarrollo sin costo |

**Modelo de OpenAI.** La elección depende de lo que resulte ser el audio:

- Si las grabaciones son **estéreo**, alcanza con un modelo que dé marcas de
  tiempo, sin diarización.
- Si son **mono**, hace falta diarización. Hoy la ofrece
  `gpt-4o-transcribe-diarize`, que se apaga el 2027-02-26; antes de esa fecha
  hay que confirmar si `gpt-transcribe` (o su reemplazo) separa hablantes.

Qué formatos y marcas de tiempo devuelve `gpt-transcribe` no está documentado
en lo revisado (los tipos del SDK oficial de OpenAI 3.41.0; la documentación
web no se pudo consultar desde el entorno de desarrollo). Se confirma con la
prueba de la sección 9 antes de fijar el modelo. Como el modelo es
configurable, cambiarlo no exige tocar código.

Después se pueden sumar Deepgram, AssemblyAI, Google o un Whisper propio
(`faster-whisper`), cada uno como una estrategia más.

**Cola.** Los pedidos se guardan en `trabajos_transcripcion` y los procesa
`sync` (`SELECT … FOR UPDATE SKIP LOCKED`, varios a la vez sin pisarse).
Así un lote grande no bloquea el panel. Un error se reintenta hasta tres veces
con espera creciente; después queda en `error` con el motivo visible.

**Costo.** Antes de lanzar un lote, el panel suma la duración de las llamadas
elegidas y muestra el costo estimado de la estrategia. Cada transcripción
guarda su costo, y la página de configuración muestra el gasto del mes.

**Comparar proveedores.** Como una llamada puede tener varias
transcripciones, se puede transcribir una muestra con dos estrategias, ver
los textos lado a lado y elegir el proveedor por calidad y precio.

### 5.8 Auditorías y reportes

- Nota final = suma de (puntaje / máximo × peso) / suma de pesos × 100, salvo
  que un criterio crítico esté en cero, en cuyo caso la nota es 0.
- Una auditoría `cerrada` no se edita; se puede reabrir con una confirmación,
  y queda registrado cuándo.
- Reportes (todos con filtros de período, área y persona):
  - Detalle: una fila por auditoría con sus puntajes por criterio.
  - Resumen por persona: cantidad de auditorías, nota promedio, promedio por
    criterio y evolución mensual.
  - Exportación en Excel (`openpyxl`, una hoja por reporte) y CSV. El PDF
    queda como opcional.

### 5.9 Acceso

Un solo usuario administrador con el login actual (`APP_USERNAME`,
`APP_PASSWORD_HASH`), que ve y edita todo. No hay tabla de usuarios ni roles.
Si más adelante se necesitan, se agregan sin tocar el resto: las auditorías
solo sumarían quién las hizo.

### 5.10 Configuración nueva

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://usuario:clave@host:5432/base` |
| `TELEFONO_REGION` | `ES` |
| `ALMACEN_TIPO` | `sftp`, `local` (desarrollo) o vacío (se escucha sin guardar) |
| `FTP_HOST`, `FTP_PORT`, `FTP_USER`, `FTP_PASSWORD`, `FTP_DIR` | Acceso al servidor; con SFTP, `FTP_PORT=8023` |
| `SFTP_HUELLA_HOST` | Huella de la clave del servidor SFTP, para verificar que es el servidor correcto |
| `AUDIO_RETENCION_DIAS` | `90` |
| `TRANSCRIPCION_RETENCION_DIAS` | `1095` |
| `SYNC_INTERVALO_MINUTOS` | Frecuencia de la sincronización |
| `TRANSCRIPCION_PROVEEDOR` | Estrategia por defecto: `openai`, `alibaba`, `falsa`… |
| `TRANSCRIPCION_RESPALDO` | Estrategias a probar si falla la principal, separadas por coma |
| `TRANSCRIPCION_IDIOMA` | `es` |
| `OPENAI_API_KEY`, `OPENAI_MODELO_TRANSCRIPCION` | Credencial y modelo de OpenAI (por defecto `gpt-4o-transcribe-diarize`) |
| `OPENAI_FORMATO_RESPUESTA` | `diarized_json`, `verbose_json` o `json`, para un modelo que el código no conoce |
| `OPENAI_BASE_URL` | Por defecto `https://api.openai.com/v1` |
| `TRANSCRIPCION_VOCABULARIO` | Palabras propias separadas por coma (marcas, productos) |
| `TRANSCRIPCION_POR_CICLO` | Pedidos de la cola por ciclo de `sync`; por defecto `20` |
| `OPENAI_PRECIO_MINUTO` | Precio por minuto para el costo estimado. Sin valor, el panel no muestra costo en vez de inventarlo |
| `CLOUDTALK_CANAL_AGENTE` | `izquierdo` o `derecho`, para grabaciones estéreo; se fija tras escuchar una grabación |
| `ALIBABA_API_KEY`, `ALIBABA_REGION`, `ALIBABA_MODELO_TRANSCRIPCION` | Credencial, región y modelo de Alibaba Model Studio |

Las variables actuales se mantienen.

### 5.11 Dependencias nuevas

`sqlalchemy`, `alembic`, `psycopg[binary]`, `pydantic`,
`phonenumbers`, `openpyxl`, `paramiko`, `openai` y el SDK de Alibaba (`dashscope`) o
llamadas HTTP directas con `requests`. En el `Dockerfile`: el paquete del sistema
`ffmpeg`. Para las pruebas de base de datos: `testcontainers[postgres]` o un
Postgres de servicio en CI.

## 6. Frontend (Streamlit)

Aplicación multipágina con `st.navigation`. Todas las páginas las usa el
administrador.

| Página | Contenido |
|---|---|
| **Inicio** | Llamadas sin asignar, auditorías en borrador y última sincronización |
| **Personas** | Alta, baja y edición de asesores con su área (reemplaza la pestaña Asesores) |
| **Cuentas** | Agentes de CloudTalk y usuarios de Chatwoot (se cargan solos desde `sync`) con su regla de asignación vigente y el historial de reglas |
| **Regla de asignación** | Por cuenta: elegir la estrategia y llenar el formulario propio de esa estrategia (en `fijo_y_resto`: persona fija, sus franjas y persona del resto). Vista semanal con el horario de cada persona en colores, vigencia, y vista previa de cuántas llamadas quedan para cada uno antes de guardar |
| **Sin asignar** | Bandeja de llamadas y chats sin persona (cuentas sin regla, conversaciones de Chatwoot sin usuario asignado o cuentas con `franjas_completas`), con asignación individual o en lote. En cada llamada se ve el motivo de la asignación automática |
| **Llamadas** | Lista filtrable (fecha, persona, cuenta, dirección, duración, con transcripción, auditada o no). Al abrir una llamada: reproductor, transcripción, persona asignada (editable), botón «Transcribir» (con el proveedor por defecto o uno elegido) y botón «Auditar». Desde la lista se eligen varias llamadas y se transcriben en lote, viendo antes el costo estimado |
| **Historial del cliente** | Buscar por número. Línea de tiempo con chats y llamadas por fecha, con quién atendió cada uno. Se abre cada elemento y se audita desde ahí |
| **Auditar** | Audio y transcripción (o mensajes del chat) a la izquierda; ficha con los criterios, puntajes y comentarios a la derecha. Guardar borrador o cerrar. Muestra la nota en vivo |
| **Auditorías** | Lista de auditorías con filtros; abrir una muestra el detalle y el audio guardado (o, pasados los 3 meses, el aviso de que ya no está y la transcripción; pasados los 3 años, solo la nota y los comentarios) |
| **Reportes** | Elegir período, área y persona; ver la tabla y un gráfico de evolución; descargar Excel o CSV |
| **Fichas** | Crear y editar fichas y criterios (nombre, peso, puntaje máximo, crítico). Editar una ficha en uso crea una versión nueva |
| **Transcripción** | Proveedor por defecto y de respaldo, estado de la cola (pendientes, errores con reintento), gasto del mes por proveedor y comparación lado a lado de dos transcripciones de la misma llamada |
| **Exportar datos** | Los CSV de Chatwoot y CloudTalk de hoy, ahora leídos de la base |

Criterios comunes a todas las páginas:

- Las fechas y horas se muestran en `Europe/Madrid`.
- Las páginas leen de la base, nunca de las APIs, así que cargan rápido. La
  única excepción es la primera escucha de una grabación.
- El audio se cachea por sesión (`st.cache_data`) para adelantar y retroceder
  sin volver a pedirlo.
- La transcripción se muestra como diálogo (Agente / Cliente) con la hora de
  cada intervención; al hacer clic en una línea, el audio salta a ese momento
  si el reproductor lo permite (si no, se muestra el minuto para buscarlo).
- Mientras una transcripción está en la cola, la página muestra su estado y
  se actualiza sola (`st.fragment` con intervalo).

## 7. Etapas

| # | Etapa | Backend | Frontend | Resultado visible |
|---|---|---|---|---|
| 1 ✅ | Base de datos | Configuración Pydantic, SQLAlchemy, Alembic, tabla `personas`, importación de `asesores.csv` | Pestaña Asesores leyendo de la base | La app funciona igual, pero con Postgres |
| 2 ✅ | Asesores y asignación | Servicios de personas y cuentas; interfaz Strategy de asignación, registro, contexto y estrategias `dueno_unico`, `fijo_y_resto` y `franjas_completas` con sus pruebas | Páginas Personas, Cuentas y Regla de asignación | Se cargan las reglas de cada cuenta |
| 3 ✅ | Sincronización | Proceso `sync` para CloudTalk y Chatwoot, teléfonos, asignación automática | Inicio, Sin asignar, Llamadas (sin audio), Exportar datos | Las llamadas y chats aparecen solos y asignados |
| 4 ✅ | Historial del cliente | Consulta por teléfono | Página Historial del cliente | Traza completa por número |
| 5 ✅ | Audio | Grabación de CloudTalk, MP3, SFTP, reintentos y retención de 3 meses | Reproductor en Llamadas e Historial | Se escuchan las llamadas |
| 6 ✅ | Transcripción | Interfaz Strategy, registro, contexto, estrategias `falsa` y `openai` (Alibaba queda para después), cola en `sync`, retención de 3 años | Botón Transcribir, lote con costo, página Transcripción | Las llamadas tienen texto |
| 7 | Auditorías | Fichas, auditorías y cálculo de nota | Fichas, Auditar y Auditorías | Se audita |
| 8 | Reportes | Reportes y Excel | Reportes | Se descarga el reporte de auditorías |

Cada etapa se entrega con pruebas y se puede desplegar por separado.

Cada etapa crea solo las tablas que usa, con su propia migración de Alembic.
La etapa 3 creó `clientes`, `llamadas`, `conversaciones` y
`puntos_sincronizacion`; las columnas de audio y transcripción de `llamadas`
llegan con las etapas 5 y 6.

Decisiones de la etapa 3:

- La app pasó a varias páginas (`st.navigation`) en tres grupos: Auditoría,
  Configuración y Reportes en vivo.
- Los CSV que leen de la base se descargan desde Llamadas y Conversaciones. Los
  tres reportes contra las APIs siguen como «Reportes en vivo», sin cambios,
  porque el de CloudTalk incluye la transcripción de Conversation
  Intelligence, que no se guarda en la base.
- Las conversaciones se releen los últimos `CHATWOOT_DIAS_RELECTURA` días en
  cada ciclo: el filtro de Chatwoot que usa el cliente actual es por fecha de
  creación, y una conversación cambia después de creada.
- Cada llamada y conversación guarda lo que devolvió la API (`datos_origen`),
  para no tener que volver a pedirlo si después hace falta otro campo.

Decisiones de la etapa 4:

- Los mensajes de cada conversación se guardan en `conversaciones.mensajes`
  (migración 0004): la sincronización ya los pedía para la dirección y el
  cierre, y así el chat se lee en el historial sin volver a pedirlo a Chatwoot.
  También se piden para las conversaciones que todavía no los tienen.
- La búsqueda por teléfono acepta cualquier formato o una parte del número, y
  también busca por nombre del cliente.
- Auditar desde el historial llega con la etapa 7; por ahora el historial
  permite cambiar el asesor y abrir la interacción en su plataforma.

Decisiones de la etapa 5:

- El audio se pide recién cuando alguien toca «Escuchar», no al elegir la fila:
  así no se gastan peticiones de CloudTalk ni espacio en llamadas que nadie
  escucha.
- Una grabación estéreo se guarda en MP3 estéreo (64 kbps) para conservar la
  separación de canales que usa la transcripción; una mono, en mono (32 kbps).
- Los MP3 que no se pudieron subir quedan en la tabla `audios_pendientes`, no en
  disco: la app y `sync` son contenedores distintos. `sync` los reintenta en
  cada ciclo (tarea `audios_pendientes`) y una vez por día borra los vencidos
  (tarea `retencion_audios`); las dos se ven en Inicio.
- Sin `ALMACEN_TIPO`, las llamadas se escuchan igual pero no se guardan.
- Una llamada más vieja que el plazo (o cuyo audio ya se borró) se escucha si
  CloudTalk todavía la tiene, pero no se vuelve a guardar.
- El servidor SFTP se verifica por su huella (`SFTP_HUELLA_HOST`), que se
  obtiene una vez con `python -m panel.audio.huella HOST PUERTO`.
- La excepción de «no borrar el audio de una auditoría en borrador» llega con
  las auditorías, en la etapa 7.

Decisiones de la etapa 6:

- Proveedor inicial: OpenAI con `gpt-4o-transcribe-diarize`, porque es el único
  modelo que hoy separa hablantes y da marcas de tiempo, y sirve tanto para
  grabaciones mono como estéreo. Está anunciado para apagarse el 2027-02-26:
  antes de esa fecha se cambia `OPENAI_MODELO_TRANSCRIPCION` (y, si el modelo
  nuevo no es conocido, `OPENAI_FORMATO_RESPUESTA`), sin tocar código.
- La estrategia de OpenAI usa `requests` directamente y no el SDK, como el
  resto de los clientes del proyecto; así se prueba con `responses`.
- Una sola llamada se transcribe en el momento desde el detalle; los lotes van
  a la cola (`trabajos_transcripcion`) y los procesa `sync`.
- En mono, el proveedor separa las voces («A», «B») sin saber cuál es el
  agente: el auditor lo elige con un clic. No se intenta adivinarlo.
- Si la estrategia no da marcas de tiempo, un estéreo se transcribe mezclado en
  vez de por canal.
- Un audio que supera lo que acepta el proveedor se parte en tramos. Con
  diarización, las etiquetas «A»/«B» de un tramo no tienen por qué coincidir con
  las del siguiente; con 25 MB por tramo (unos 100 minutos en mono) es un caso
  raro.
- El costo estimado de un lote se calcula con la duración de las llamadas; una
  grabación estéreo se transcribe por canal y cuesta el doble.
- La página donde se ve la fila elegida la recuerda por su id: Streamlit la
  olvida cuando cambian los datos de la tabla (al transcribir o asignar).
- El modelo se elige al transcribir (una llamada o un lote). Cada estrategia
  publica sus `modelos` y da una variante con `con_modelo`, con las capacidades
  y el precio de ese modelo; el servicio y las pantallas no conocen los modelos
  de ningún proveedor. El pedido de la cola guarda el modelo (migración 0007).
  Con un modelo elegido a mano no se usa el respaldo: se pidió ese.
- Los precios siguen en la configuración (ningún proveedor los da por API),
  pero se comprueban con lo cobrado: una fuente de facturación por proveedor
  (`panel/transcripcion/facturacion.py`, para OpenAI las APIs de uso y costos
  con una Admin key) da segundos y USD por modelo, y el panel calcula el precio
  real. No se guarda nada en la base: se consulta y se cachea una hora.
La etapa 1 creó `personas`; las demás tablas de la sección 5.2 llegan con su
etapa.

## 8. Pruebas

- Funciones puras (asignación, teléfonos, nota, armado de reportes): pruebas
  unitarias con `pytest`, como hoy.
- Servicios con base de datos: contra un Postgres real de prueba, no SQLite,
  porque se usan `EXCLUDE`, `JSONB` y `timestamptz`.
- Clientes de API: simulados con `responses`. Almacén: el mismo juego de
  pruebas corre contra `local` y contra un servidor SFTP de prueba.
- Transcripción: un mismo juego de pruebas de contrato que corre contra cada
  estrategia con respuestas grabadas del proveedor (formato común, hablantes,
  errores y límites). El contexto se prueba con la estrategia `falsa`: partir
  audios largos, separar canales, respaldo cuando falla la principal y
  reintentos de la cola.
- Migraciones: una prueba que aplica todas desde cero.

## 9. Pendientes

1. La ficha de calidad: ¿ya existe con sus criterios y pesos, o se arma?
2. **Prueba con grabaciones reales antes de fijar el modelo de OpenAI.**
   Descargar unas 20 grabaciones de CloudTalk y ver: si son mono o estéreo (y,
   si son estéreo, qué canal es el agente), qué devuelve `gpt-transcribe` en
   formatos y marcas de tiempo, cómo separa hablantes
   `gpt-4o-transcribe-diarize`, y el costo real por minuto.
3. ¿Cuánto espacio en disco tiene el plan del hosting? ¿El puerto 8023 de
   SFTP está abierto en el firewall del hosting?
4. ¿Cuánto tiempo guarda CloudTalk las grabaciones en el plan contratado?
5. Protección de datos: los clientes están en España (RGPD). Enviar audio a
   un proveedor externo necesita su acuerdo de tratamiento de datos y elegir
   una región adecuada (en Alibaba, la internacional o la europea si existe
   para el modelo elegido). Hay que confirmarlo antes de usar audio real.
   Conviene también que confirme los plazos de 3 meses para los audios y 3
   años para las transcripciones.
