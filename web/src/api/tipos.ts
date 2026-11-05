// Formas de los datos que devuelve la API (espejo de los modelos de Python).

export type TipoInteraccion = "llamada" | "conversacion";

export interface Persona { id: number; correo: string; nombre: string | null; area: string; activa: boolean }
export interface Opcion { id: number; nombre: string }
export interface Catalogos { personas: Persona[]; cuentas: Record<string, Opcion[]> }

export interface FilaInteraccion {
  id: number; id_externo: string; inicio: string; cuenta: string; persona_id: number | null;
  asesor: string; area: string; asignacion: string; motivo: string; telefono: string;
  cliente: string; cliente_id: number | null;
}
export interface FilaLlamada extends FilaInteraccion {
  direccion: string; duracion_s: number | null; grabada: boolean; enlace_plataforma: string | null;
  audio_estado: string | null; transcripcion_estado: string | null;
}
export interface FilaConversacion extends FilaInteraccion {
  canal: string; estado: string; etiquetas: string; direccion: string; cierre: string | null;
  cierre_aproximado: boolean; horas_resolucion: number | null;
}
export interface Listado<T> { filas: T[]; limite: number; recortado: boolean }

export interface Resumen {
  llamadas: number; conversaciones: number; llamadas_sin_asignar: number;
  conversaciones_sin_asignar: number; cuentas_sin_regla: number;
}
export interface PuntoSync {
  fuente: string; hasta: string | null; ultimo_intento: string | null; ultimo_exito: string | null;
  ultimo_error: string | null; resumen: Record<string, unknown> | null;
}
export interface EstadoConfig {
  cloudtalk: boolean; chatwoot: boolean; almacen: string; transcripcion: boolean;
  tope_mensual_usd: number | null; aviso_porcentaje: number; retencion_audio_dias: number;
  intervalo_minutos: number; error_ajustes: string | null; ajustes_ilegibles: string[];
  chatwoot_conversacion: string | null;
}
export interface Inicio {
  ahora: string; semana: Resumen; semana_anterior: Resumen; sincronizacion: PuntoSync[];
  cola: Record<string, number>; audios_por_vencer: number; gasto_mes_usd: number; config: EstadoConfig;
}

export interface Mensaje { fecha: string | null; rol: "cliente" | "asesor" | "nota" | "actividad"; autor: string; texto: string }

export interface Segmento { hablante: "agente" | "cliente" | "desconocido"; etiqueta: string | null; inicio: number | null; fin: number | null; texto: string }
export interface VersionTranscripcion {
  id: number; proveedor: string; modelo: string; canales_audio: string; segmentos: Segmento[];
  duracion_audio: number | null; costo_estimado: string | null; principal: boolean; creado_en: string;
  // Para las voces sin resolver: cuál parece el agente según sus frases.
  sugerencia: { etiqueta: string; frase: string } | null;
}
export interface OpcionModelo { clave: string; titulo: string; devuelve: string; costo_usd: number | null }
export interface PedidoLlamada { id: number; estado: "pendiente" | "en_proceso" | "hecho" | "error"; intentos: number; error: string | null }
export interface TranscripcionesLlamada { configurada: boolean; versiones: VersionTranscripcion[]; opciones: OpcionModelo[]; pedido: PedidoLlamada | null }
export interface CostoLote { llamadas: number; minutos: number; costo_usd: number | null; requiere_confirmacion: boolean; umbral_usd: number | null; modelo: string | null }

export interface ResumenCliente { id: number; telefono: string; nombre: string | null; revisar: boolean; llamadas: number; conversaciones: number; ultima: string | null }
export interface ElementoHistorial {
  tipo: TipoInteraccion; id: number; id_externo: string; inicio: string; cuenta: string; persona_id: number | null;
  asesor: string; asignacion: string; motivo: string; resumen: string; enlace_plataforma: string | null;
  finalizacion: boolean;
}
export interface Historial { cliente: ResumenCliente; elementos: ElementoHistorial[]; por_asesor: Record<string, number> }

export interface Prueba { ok: boolean; mensaje: string }
export interface ValorAjuste { valor: string; secreto: boolean; origen: "panel" | "entorno" | null }

export interface TrabajoConError { id: number; llamada_id: number; llamada: string; inicio: string; intentos: number; error: string; modelo: string | null }
export interface TrabajoEnCola extends TrabajoConError { estado: "pendiente" | "en_proceso" }
export interface ResumenTranscripcion {
  configurada: boolean; cola: Record<string, number>; gasto_mes_usd: number; tope_mensual_usd: number | null;
  aviso_porcentaje: number; por_ciclo: number; intervalo_minutos: number; auto_min_segundos: number;
  errores: TrabajoConError[]; abiertos: TrabajoEnCola[]; costo_reintento_usd: number | null; modelos: OpcionModelo[];
  procesador: EstadoProcesador | null; procesando_en_panel: boolean;
}
// Quién vacía la cola (el servicio de sincronización) y cuándo lo hizo por última vez.
export interface EstadoProcesador {
  ultima_vuelta: string | null; ultimo_exito: string | null; ultimo_error: string | null;
  resumen: Record<string, unknown> | null; sincronizacion: string | null; diagnostico: string | null;
}
export interface FilaGasto {
  proveedor: string; modelo: string; titulo: string; minutos_panel: number; usd_estimado: number | null;
  minutos_cobrados: number | null; usd_cobrados: number | null; precio_configurado: number | null;
  precio_real: number | null; diferencia: number | null; desviado: boolean;
}
export interface LlamadaComparable { llamada_id: number; llamada: string; inicio: string; transcripciones: number }
export interface ModeloTranscripcion { proveedor: string; modelo: string; precio_minuto: string | number | null; redondeo: "segundo" | "minuto"; activo: boolean }
export interface Proveedor { nombre: string; titulo: string; variable_clave: string | null; clave_mascara: string; origen_clave: string | null; modelos_conocidos: Record<string, string> }
export interface CobrosTraidos { proveedor: string; titulo: string; ok: boolean; mensaje: string }
export interface ModeloDisponible { modelo: string; devuelve: string }
export interface ConfiguracionTranscripcion {
  proveedores: Proveedor[]; modelos: ModeloTranscripcion[]; principal: string | null; respaldo: string[];
  idioma: string; vocabulario: string[]; frases_agente: string[]; canal_agente: string; auto_min_segundos: number;
  tope_mensual_usd: number | null; aviso_porcentaje: number; confirmar_lote_usd: number | null;
}

export interface Estrategia { nombre: string; titulo: string; descripcion: string }
export interface FilaCuenta { id: number; plataforma: string; nombre: string; correo: string | null; estrategia: string | null; detalle: string[]; aviso: string; vigente_desde: string | null }
export interface ReglaHistorica { estrategia: string; desde: string; hasta: string; detalle: string[] }
export interface DetalleCuenta {
  id: number; nombre: string; plataforma: string; estrategia: string | null; parametros: Record<string, unknown> | null;
  horario: (string | null)[][]; historial: ReglaHistorica[]; ultima_estrategia: string | null; ultimos_parametros: Record<string, unknown> | null;
}
export interface ResumenReasignacion { revisadas: number; cambiaron: number; por_persona: Record<string, number> }
