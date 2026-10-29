# Panel de auditorías de calidad — Patrones de diseño

Fecha: 2026-10-29
Estado: propuesto
Complementa a: `2026-10-28-auditorias-calidad-design.md`

## 1. Objetivo

Que agregar una forma nueva de hacer algo (otro proveedor de transcripción,
otra regla para repartir una cuenta, otro servidor de audio, otra plataforma de
llamadas) sea **sumar una pieza**, nunca reescribir ni borrar la lógica que ya
funciona.

Este documento dice, para cada parte del sistema, qué patrón se usa, por qué
es el adecuado frente a las alternativas, y qué se toca y qué no al agregar una
implementación nueva.

## 2. Principios comunes

Todas las partes siguen las mismas seis reglas. Son las que hacen que los
patrones funcionen juntos y no sean solo nombres.

### 2.1 Abierto para extender, cerrado para modificar

La lógica común (el «contexto») depende de una **interfaz**, nunca de una
implementación concreta. Una implementación nueva es una clase nueva que
cumple esa interfaz. El contexto, la base de datos y las pantallas no cambian.

### 2.2 Interfaces pequeñas, definidas con `Protocol`

Cada interfaz tiene los métodos mínimos que el contexto necesita. Se definen
con `typing.Protocol`: una implementación solo tiene que tener esos métodos,
sin heredar de una clase base. Si una interfaz empieza a crecer con métodos
que solo usa una implementación, es señal de que hay que partirla.

### 2.3 Datos que cruzan una frontera: modelos Pydantic

Lo que entra y sale de una interfaz son modelos Pydantic (por ejemplo,
`Transcripcion`, `ResultadoAsignacion`, `LlamadaExterna`), nunca el JSON de un
proveedor. Así:

- El contexto nunca ve formatos ajenos: si OpenAI cambia su respuesta, se
  corrige solo su estrategia.
- Los parámetros de cada implementación también son un modelo Pydantic: se
  validan al guardarlos y al leerlos, y una configuración mal cargada falla con
  un mensaje claro en vez de en medio de un proceso.

### 2.4 Registro por nombre y raíz de composición

- Cada familia de implementaciones tiene un **registro**: un diccionario
  nombre → clase, que se llena con un decorador
  (`@registrar("openai")`). Agregar una implementación es escribir el archivo
  y decorar la clase; no hay un `if/elif` central que editar.
- Un único módulo, la **raíz de composición** (`panel/composicion.py`), lee la
  configuración y arma las piezas concretas: qué estrategia de transcripción,
  qué almacén de audio, qué respaldo. Es el **único** lugar del sistema que
  conoce clases concretas; el resto recibe interfaces ya armadas
  (inyección de dependencias por constructor, sin librerías extra).
- En la base se guarda el **nombre** de la implementación y sus parámetros
  (JSONB), no columnas propias de cada una. Una implementación nueva **no
  necesita migración** de base de datos.

### 2.5 Nada se borra mientras haya historia que lo use

Una implementación que deja de usarse (un modelo de OpenAI que se apaga, una
regla de asignación vieja) se marca como **retirada** en el registro: ya no se
ofrece para casos nuevos, pero sigue disponible para leer, recalcular o
explicar los datos que se generaron con ella. Por eso:

- Las reglas de asignación tienen vigencia y guardan su estrategia: una
  llamada de 2026 se explica con la regla de 2026.
- Cada transcripción guarda qué proveedor y qué modelo la hizo.
- Las fichas de auditoría se versionan: cambiar criterios crea una versión
  nueva y las auditorías viejas conservan la suya.

### 2.6 Pruebas de contrato

Para cada interfaz hay **un juego de pruebas de contrato** que corre contra
todas sus implementaciones (con `pytest.mark.parametrize`). Una implementación
nueva hereda esas pruebas desde el primer día: si las pasa, el contexto puede
usarla sin sorpresas. Esto es lo que garantiza que «sumar una pieza» no rompa
lo demás.

## 3. Resumen

| Parte del sistema | Patrón principal | Patrones de apoyo |
|---|---|---|
| Transcripción | **Strategy** | Adapter, Registry, Decorator, Chain of Responsibility |
| Preparación del audio (mono / estéreo) | **Strategy** elegida por una **Factory** | — |
| Asignación de cuentas compartidas | **Strategy** | Registry, parámetros tipados, vigencia |
| Fuentes de datos (CloudTalk, Chatwoot) | **Adapter** | Template Method en la sincronización |
| Almacén de audio | **Adapter** (puertos y adaptadores) | — |
| Acceso a datos | **Repository** + **Unit of Work** | — |
| Cola de transcripción | **Command** | Productor / consumidor |
| Retención | **Strategy** (una política por tipo de dato) | — |
| Cálculo de la nota | **Strategy** | — |
| Exportación de reportes | **Strategy** (un exportador por formato) | — |
| Avance y avisos de procesos largos | **Observer** (callbacks) | — |

Las secciones siguientes explican cada una.

## 4. Transcripción

**Problema.** Hay varios proveedores (OpenAI ahora; Alibaba, Deepgram u otros
después), cada uno con su API, sus formatos, sus límites y sus precios.
Además, los modelos de un mismo proveedor se apagan: casi todos los de OpenAI
tienen apagado anunciado para el 2027-02-26.

**Patrón: Strategy.** Una interfaz `EstrategiaTranscripcion` con
`transcribir(audio, opciones) -> Transcripcion`, `capacidades` y
`costo_estimado(duracion)`. Cada proveedor es una estrategia. El contexto
(`ServicioTranscripcion`) hace todo lo común: obtener el audio, prepararlo,
elegir estrategia, guardar el resultado.

**Por qué Strategy y no otra cosa:**

- Un `if proveedor == "openai": … elif …` en el servicio obliga a editar la
  lógica central con cada proveedor nuevo y mezcla los detalles de todos.
- La herencia con una clase base grande (Template Method puro) ata a todos
  los proveedores a los mismos pasos, y no todos los tienen: Alibaba trabaja
  con una URL y en forma asíncrona, OpenAI con el archivo y en forma
  síncrona.
- Strategy deja que cada proveedor resuelva su llamada a su manera y solo
  exige el mismo resultado.

**Patrones de apoyo:**

- **Adapter:** cada estrategia traduce la respuesta del proveedor al modelo
  común `Transcripcion` (segmentos con hablante, inicio, fin y texto). Dentro
  de la estrategia de OpenAI, cada formato (`diarized_json`, `verbose_json`,
  `json`) tiene su propio traductor.
- **Capacidades declaradas:** cada estrategia declara si separa hablantes, si
  da marcas de tiempo, su tamaño máximo y si requiere URL. El contexto decide
  con esos datos y **nunca pregunta por el nombre del proveedor**. Esto es lo
  que permite sumar un proveedor sin tocar el contexto.
- **Decorator:** lo que vale para todos los proveedores se agrega envolviendo
  una estrategia, sin tocarla:
  `ConReintentos(ConLimiteDeRitmo(ConRegistroDeCosto(EstrategiaOpenAI(...))))`.
  Cada envoltorio cumple la misma interfaz, así que el contexto no se entera.
- **Chain of Responsibility:** la cadena principal → respaldo. Si una
  estrategia falla o no cumple las capacidades que pide el audio, se pasa a la
  siguiente.

**Agregar un proveedor nuevo:** se crea `transcripcion/estrategias/<nombre>.py`
con su clase, sus parámetros y su traductor, se decora con
`@registrar("<nombre>")`, se agregan sus variables de entorno y se corren las
pruebas de contrato. **No se toca:** el contexto, la cola, la base, las
pantallas ni las otras estrategias.

**Cambiar de modelo** (por ejemplo, cuando OpenAI apague uno): es cambiar
`OPENAI_MODELO_TRANSCRIPCION`. Si el modelo nuevo devuelve otro formato, se
suma un traductor; los existentes se conservan.

## 5. Preparación del audio (mono o estéreo)

**Problema.** CloudTalk solo garantiza WAV. Cada archivo puede ser mono,
estéreo real (un canal por persona) o estéreo con los dos canales iguales, y
cada caso se transcribe distinto.

**Patrón: Strategy elegida por una Factory.** Una interfaz `PreparadorAudio`
con `preparar(wav) -> PlanDeTranscripcion`. Hay tres preparadores:
`Mono`, `EstereoPorCanal` y `EstereoDuplicado` (este último delega en `Mono`).
Una fábrica inspecciona el WAV (canales y si son iguales) y devuelve el
preparador que corresponde.

El `PlanDeTranscripcion` dice qué audios transcribir, qué hablante es cada uno
si se sabe, y qué capacidades necesita la estrategia de transcripción
(marcas de tiempo para el estéreo, diarización para el mono). Así este paso y
el de transcripción quedan desacoplados: se cruzan solo a través de las
capacidades.

**Por qué este patrón:** la decisión es **por archivo**, no por configuración,
así que hace falta algo que elija en tiempo de ejecución (la fábrica) y una
forma intercambiable de actuar (la estrategia). Si mañana aparece un caso nuevo
(por ejemplo, grabaciones con tres canales en una conferencia), se suma un
preparador y una regla en la fábrica.

**No se toca:** las estrategias de transcripción ni el contexto.

## 6. Asignación de cuentas compartidas

**Problema.** Una cuenta (agente de CloudTalk o usuario de Chatwoot) puede
tener un dueño o ser compartida, y hay varias formas de repartirla: hoy, «uno
fijo y el resto al otro»; mañana, quizá turnos desde un Excel.

**Patrón: Strategy.** Interfaz `EstrategiaAsignacion` con
`asignar(interaccion, parametros) -> ResultadoAsignacion` y
`validar(parametros)`. Estrategias iniciales: `dueno_unico`, `fijo_y_resto` y
`franjas_completas`. El contexto (`ServicioAsignacion`) hace lo común:
respetar lo manual, buscar la regla vigente en la fecha de la interacción,
convertir la hora a España y guardar persona, regla y motivo.

**Por qué Strategy:**

- Cada cuenta puede usar una forma distinta de repartir, y cambiarla en el
  tiempo: la regla elige la estrategia **por cuenta y por período**, que es
  exactamente lo que resuelve Strategy.
- Las estrategias son **funciones puras**: reciben la hora y los parámetros y
  devuelven la persona. No tocan la base ni la zona horaria. Se prueban sin
  base de datos y sin fechas reales.
- Una tabla de reglas con columnas fijas (persona fija, persona resto,
  franjas…) obligaría a migrar la base con cada forma nueva de repartir. Con
  nombre + parámetros JSONB validados por Pydantic, no.

**Agregar una estrategia nueva:** se crea el archivo con su clase y su modelo
de parámetros, se registra, se suma el formulario de sus parámetros en la
página *Regla de asignación* (cada estrategia trae su propio formulario) y se
corren las pruebas de contrato. **No se toca:** el contexto, la sincronización,
la bandeja *Sin asignar* ni las reglas ya guardadas.

**Lo que no se borra:** una estrategia que ya no se usa queda registrada como
retirada mientras exista alguna regla histórica que la nombre.

## 7. Fuentes de datos (CloudTalk y Chatwoot)

**Problema.** Cada plataforma tiene su API, su paginación, sus límites y sus
nombres de campos. La sincronización tiene que guardar todo con la misma
forma. Hoy son CloudTalk y Chatwoot; Ringover u otra podría volver.

**Patrón: Adapter.** Cada plataforma tiene un adaptador que implementa una
interfaz de fuente: `FuenteLlamadas` (`llamadas_desde(punto) ->
list[LlamadaExterna]`, `grabacion(id) -> bytes | None`) y
`FuenteConversaciones` (`conversaciones_desde(punto) ->
list[ConversacionExterna]`). Los clientes HTTP actuales (`cloudtalk.py`,
`chatwoot.py`) se conservan; el adaptador los usa y traduce a los modelos
comunes.

**Template Method en la sincronización:** el ciclo es igual para todas las
fuentes (leer el último punto, traer lo nuevo con margen, guardar con
*upsert*, normalizar teléfonos, asignar, avanzar el punto). Ese esqueleto está
una sola vez; cada fuente solo aporta el paso de «traer lo nuevo».

**Por qué Adapter y no usar los clientes directamente:** si la sincronización
leyera `Cdr.started_at` o `meta.sender.phone_number`, cada plataforma nueva
obligaría a editar la sincronización. Con el adaptador, los nombres de campos
de cada API quedan encerrados en un solo archivo.

**Agregar una plataforma:** un cliente HTTP, un adaptador y su registro. **No
se toca:** la sincronización, la asignación, la base ni las pantallas.

## 8. Almacén de audio

**Problema.** Hoy el audio va al hosting por SFTP; podría ser una carpeta
local para desarrollo, FTPS o S3 cuando venza el año del hosting.

**Patrón: Adapter (puertos y adaptadores).** Interfaz `AlmacenAudio` con
`subir`, `bajar`, `existe` y `borrar`. Implementaciones: `sftp` y `local`. En la
base se guarda la ruta relativa, nunca el servidor.

Los pendientes de subir no quedaron como un decorador sobre el almacén, como
se había previsto, sino en el servicio de audio y en la tabla
`audios_pendientes`: la app y la sincronización corren en contenedores
distintos, así que un pendiente en el disco de la app no lo vería nunca la
sincronización. La caché de lo escuchado vive en la sesión de Streamlit.

**Por qué:** la lógica de audio (escuchar, convertir, retener) no sabe dónde
están los archivos. Cambiar de servidor es configuración más una copia de
archivos.

**Agregar un destino (por ejemplo S3):** una clase nueva, su registro y sus
variables. Las mismas pruebas de contrato corren contra todos los destinos.

## 9. Acceso a datos

**Patrón: Repository + Unit of Work.**

- **Repository:** cada agregado tiene un repositorio
  (`RepositorioLlamadas`, `RepositorioReglas`, `RepositorioAuditorias`…) con
  consultas con nombre propio (`sin_asignar(desde, hasta)`,
  `regla_vigente(cuenta, fecha)`). Los servicios no escriben SQL ni conocen
  SQLAlchemy.
- **Unit of Work:** la sesión de SQLAlchemy ya lo es. Cada operación del
  panel o ciclo de sincronización abre una unidad de trabajo y la confirma o
  la deshace entera; nunca quedan datos a medias.

**Por qué:** las pantallas y los servicios se prueban con repositorios en
memoria, y una consulta lenta se optimiza en un solo lugar sin tocar a quienes
la usan.

**Dónde no se usa:** los reportes complejos usan consultas propias en un
módulo de reportes, porque forzarlos dentro de un repositorio genérico los
complica sin beneficio.

## 10. Cola de transcripción

**Patrón: Command** (con productor y consumidor). Cada pedido de transcripción
es un comando guardado en la base (`trabajos_transcripcion`): qué llamada, con
qué estrategia, quién lo pidió, en qué estado está, cuántos intentos lleva.
El panel produce comandos; `sync` los consume.

**Por qué:** el pedido sobrevive a un reinicio, se puede reintentar, se ve su
estado y su error, y un lote grande no bloquea el panel. Si después aparece
otro trabajo largo (por ejemplo, recalcular todas las asignaciones de un año),
se suma como otro tipo de comando con el mismo mecanismo.

## 11. Retención

**Patrón: Strategy**, una política por tipo de dato: `PoliticaRetencionAudio`
(90 días, borra en el almacén) y `PoliticaRetencionTranscripcion` (3 años,
borra en la base). La tarea diaria recorre la lista de políticas registradas;
cada una sabe qué está vencido, qué excepciones tiene (no borrar audio de una
auditoría en borrador) y cómo borrarlo.

**Por qué:** si mañana se decide un plazo para los mensajes de Chatwoot, se
suma una política. La tarea diaria y las otras políticas no cambian, y cada
una se prueba sola con fechas fijas.

## 12. Cálculo de la nota

**Patrón: Strategy**, de alcance chico. La ficha guarda qué método de cálculo
usa. El primero es «ponderado con criterio crítico» (sección 5.8 del plan).
Si el equipo de calidad quiere otro (por ejemplo, por cumplimiento sí/no), se
suma un método; las auditorías viejas siguen calculadas con el suyo porque la
ficha está versionada.

## 13. Exportación de reportes

**Patrón: Strategy**, un exportador por formato (`excel`, `csv`, y `pdf` más
adelante) con `exportar(reporte) -> bytes`. El armado de los datos del
reporte es uno solo; cada exportador solo decide cómo se escribe.

## 14. Avance y avisos de procesos largos

**Patrón: Observer** con callbacks, como ya hace el código actual
(`al_avanzar`, `al_esperar`). Los servicios avisan «llevo 40 de 300» o
«espero 60 s por el límite» sin saber si quien escucha es una barra de
Streamlit, un log de `sync` o una prueba.

## 15. Dónde no se usan patrones

Sumar abstracciones donde no hay variación hace el código más difícil de
leer. Estas partes quedan como funciones simples hasta que aparezca una
segunda forma real de hacerlas:

- Normalización de teléfonos: una función con `phonenumbers` y región `ES`.
- Configuración: un modelo Pydantic (`config.py`).
- Conversión de horas a `Europe/Madrid`: una función en el contexto de
  asignación.
- Conversión WAV → MP3: una función que llama a `ffmpeg`.

La regla para decidir: **se abstrae cuando hay o se espera con certeza una
segunda implementación**, no por las dudas.

## 16. Cómo se ve agregar algo nuevo (ejemplos)

| Cambio | Qué se agrega | Qué no se toca |
|---|---|---|
| Transcribir con Alibaba | `transcripcion/estrategias/alibaba.py` y sus variables | Contexto, cola, base, pantallas, estrategia de OpenAI |
| OpenAI apaga `gpt-4o-transcribe-diarize` | Cambiar `OPENAI_MODELO_TRANSCRIPCION`; si el formato nuevo es distinto, un traductor más | Todo lo demás; las transcripciones viejas siguen diciendo qué modelo las hizo |
| Turnos cargados desde un Excel | Estrategia de asignación `turnos_excel` con su formulario | Las reglas `fijo_y_resto` existentes, la sincronización, la bandeja |
| Volver a usar Ringover | Adaptador `FuenteLlamadas` para Ringover (el cliente HTTP ya existe) | Sincronización, asignación, transcripción, base |
| Pasar los audios a S3 | `AlmacenAudio` para S3 y copiar los archivos | Audio, retención, base (las rutas son relativas) |
| Plazo de retención para chats | `PoliticaRetencionMensajes` | La tarea diaria y las otras políticas |
| Reporte en PDF | Exportador `pdf` | El armado del reporte y los otros formatos |
