// Llamadas y Conversaciones: la misma pantalla con otra Vista (qué columnas,
// qué enlace a la plataforma y qué se ve en el detalle).

import { Fragment, useDeferredValue, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, consulta } from "../api/cliente";
import type { CostoLote, EstadoConfig, FilaConversacion, FilaInteraccion, FilaLlamada, Listado, TipoInteraccion } from "../api/tipos";
import { Aviso, Boton, BotonDescarga, BotonEnlace, Cabecera, Cargando, ErrorCarga, Icono, Insignia, Tarjeta, type Tono } from "../componentes/basicos";
import { Tabla, type Columna } from "../componentes/Tabla";
import { BarraFiltros, useCatalogos, useFiltros } from "../componentes/filtros";
import { EditorAsignacion, FranjaAsesor, origenAsignacion } from "../componentes/asignacion";
import { PanelLlamada } from "../componentes/Llamada";
import { Chat } from "../componentes/Chat";
import { Marcador } from "../componentes/campos";
import { useAvisos } from "../componentes/avisos";
import { capitalizar, duracion, entero, formatoFechaHora, numero, telefono, usd } from "../utilidades/formato";

const AUDIO: Record<string, [string, Tono]> = {
  guardado: ["Guardado", "ok"], pendiente: ["Guardándose", "cola"], sin_grabacion: ["Sin grabación", "error"],
  vencido: ["CloudTalk lo borró", "nada"], eliminado: ["Borrado por plazo", "nada"],
};
const TRANSCRIPCION: Record<string, [string, Tono]> = { transcrita: ["Hecha", "ok"], eliminada: ["Borrada por plazo", "nada"] };

const comunes = <T extends FilaInteraccion>(): Columna<T>[] => [
  { titulo: "Fecha", celda: (f) => <span className="mono">{formatoFechaHora(f.inicio)}</span> },
  { titulo: "Asesor", celda: (f) => <b style={{ color: f.asesor ? undefined : "var(--sin-texto)" }}>{f.asesor || "Sin asignar"}</b> },
  { titulo: "Asignación", celda: (f) => { const o = origenAsignacion(f.asesor, f.asignacion); return <Insignia tono={o.tono}>{o.texto}</Insignia>; } },
  { titulo: "Motivo", celda: (f) => <span className="cap" style={{ color: "var(--etiqueta)" }}>{f.motivo}</span> },
  { titulo: "Cliente", celda: (f) => f.cliente },
  { titulo: "Teléfono", celda: (f) => <span className="mono">{telefono(f.telefono)}</span> },
];
const finales = <T extends FilaInteraccion>(): Columna<T>[] => [
  { titulo: "Cuenta", celda: (f) => f.cuenta },
  { titulo: "Área", celda: (f) => f.area },
];

interface Vista<T extends FilaInteraccion> {
  tipo: TipoInteraccion; titulo: string; singular: string; plural: string; plataforma: string; icono: string;
  subtitulo: string; columnas: Columna<T>[];
  enlace: (fila: T, estado?: EstadoConfig) => { texto: string; url: string } | null;
  datos: (fila: T) => [string, ReactNode][];
}

export const VISTA_LLAMADAS: Vista<FilaLlamada> = {
  tipo: "llamada", titulo: "Llamadas", singular: "Llamada", plural: "llamadas", plataforma: "cloudtalk", icono: "call",
  subtitulo: "CloudTalk · elija una fila para escucharla, transcribirla o reasignarla",
  columnas: [
    ...comunes<FilaLlamada>(),
    { titulo: "Dirección", celda: (f) => <span className="fila" style={{ gap: 4 }}><Icono nombre={f.direccion === "saliente" ? "call_made" : "call_received"} tamano={16} />{capitalizar(f.direccion)}</span> },
    { titulo: "Duración", celda: (f) => <span className="mono">{duracion(f.duracion_s)}</span>, derecha: true },
    { titulo: "Audio", celda: (f) => { const a = f.audio_estado ? AUDIO[f.audio_estado] : null; return a ? <Insignia tono={a[1]}>{a[0]}</Insignia> : <span className="cap">—</span>; } },
    { titulo: "Transcripción", celda: (f) => { const t = f.transcripcion_estado ? TRANSCRIPCION[f.transcripcion_estado] : null; return t ? <Insignia tono={t[1]}>{t[0]}</Insignia> : <span className="cap">—</span>; } },
    ...finales<FilaLlamada>(),
    { titulo: "Id CloudTalk", celda: (f) => <span className="mono cap">{f.id_externo}</span> },
  ],
  enlace: (f) => (f.enlace_plataforma ? { texto: "Abrir en CloudTalk", url: f.enlace_plataforma } : null),
  datos: (f) => [["Cliente", f.cliente], ["Teléfono", telefono(f.telefono)], ["Cuenta", f.cuenta], ["Área", f.area],
    ["Dirección", capitalizar(f.direccion)], ["Duración", duracion(f.duracion_s)], ["Id CloudTalk", f.id_externo]],
};

export const VISTA_CONVERSACIONES: Vista<FilaConversacion> = {
  tipo: "conversacion", titulo: "Conversaciones", singular: "Conversación", plural: "conversaciones", plataforma: "chatwoot", icono: "chat",
  subtitulo: "Chatwoot · WhatsApp, web y correo",
  columnas: [
    ...comunes<FilaConversacion>(),
    { titulo: "Canal", celda: (f) => f.canal },
    { titulo: "Estado", celda: (f) => <Insignia tono={f.estado === "resuelta" ? "ok" : f.estado === "abierta" ? "cola" : "neutro"}>{capitalizar(f.estado)}</Insignia> },
    { titulo: "Etiquetas", celda: (f) => <span className="fila" style={{ gap: 3 }}>{f.etiquetas.split(";").filter(Boolean).map((e) => <Insignia key={e} tono="neutro">{e}</Insignia>)}</span> },
    { titulo: "Horas hasta la resolución", celda: (f) => <span className="mono">{f.horas_resolucion === null ? "—" : numero(f.horas_resolucion, 1)}</span>, derecha: true },
    ...finales<FilaConversacion>(),
    { titulo: "Id Chatwoot", celda: (f) => <span className="mono cap">{f.id_externo}</span> },
  ],
  enlace: (f, estado) =>
    estado?.chatwoot_conversacion ? { texto: "Abrir en Chatwoot", url: estado.chatwoot_conversacion.replace("{id}", f.id_externo) } : null,
  datos: (f) => [["Cliente", f.cliente], ["Teléfono", telefono(f.telefono)], ["Cuenta", f.cuenta], ["Área", f.area],
    ["Canal", f.canal], ["Estado", capitalizar(f.estado)], ["Etiquetas", f.etiquetas.replace(/;/g, ", ")],
    ["Horas hasta la resolución", f.horas_resolucion === null ? "—" : numero(f.horas_resolucion, 1)]],
};

export function PaginaInteracciones<T extends FilaInteraccion>({ vista }: { vista: Vista<T> }) {
  const [filtros, cambiar] = useFiltros(7);
  const diferidos = useDeferredValue(filtros);
  const [elegidaId, setElegidaId] = useState<number | null>(null);
  const datos = useQuery({
    queryKey: ["interacciones", vista.tipo, diferidos],
    queryFn: () => api.get<Listado<T>>(`/api/interacciones/${vista.tipo}`, { ...diferidos }),
    placeholderData: (anterior) => anterior,
  });
  const estado = useQuery({ queryKey: ["estado"], queryFn: () => api.get<EstadoConfig>("/api/estado") });
  const filas = datos.data?.filas ?? [];
  const elegida = filas.find((f) => f.id === elegidaId) ?? null;
  const sinAsesor = filas.filter((f) => !f.asesor).length;

  return (
    <>
      <Cabecera titulo={vista.titulo} subtitulo={vista.subtitulo}>
        <BotonDescarga ruta={(formato) => `/api/interacciones/${vista.tipo}/${formato}${consulta({ ...filtros })}`} />
      </Cabecera>
      <BarraFiltros filtros={filtros} cambiar={cambiar} plataforma={vista.plataforma} />
      {filtros.desde > filtros.hasta && <Aviso tipo="atencion">La fecha inicial no puede ser posterior a la final.</Aviso>}

      {vista.tipo === "llamada" && <Lote filas={filas as unknown as FilaLlamada[]} />}

      <Tarjeta>
        <div className="tarjeta-cab">
          <span className="cap">
            <b style={{ color: "var(--tinta)" }}>{entero(filas.length)} {vista.plural}</b>
            {sinAsesor > 0 && ` · ${entero(sinAsesor)} sin asignar`}
            {datos.data?.recortado && ` · se muestran las ${entero(datos.data.limite)} más recientes: acote las fechas o descargue el CSV`}
          </span>
          <span className="cap">{datos.isFetching ? "Actualizando…" : "Elija una fila para ver el detalle"}</span>
        </div>
        {datos.isLoading ? <div style={{ padding: 14 }}><Cargando filas={5} texto={`Cargando ${vista.plural}…`} /></div>
          : datos.error ? <div style={{ padding: 14 }}><ErrorCarga error={datos.error} /></div>
          : <Tabla filas={filas} columnas={vista.columnas} clave={(f) => f.id} elegida={elegidaId}
              alElegir={(f) => setElegidaId(f.id === elegidaId ? null : f.id)}
              vacio={`No hay ${vista.plural} con estos filtros.`} />}
      </Tarjeta>

      {elegida && <Detalle vista={vista} fila={elegida} estado={estado.data} alCerrar={() => setElegidaId(null)} />}
    </>
  );
}

function Detalle<T extends FilaInteraccion>({ vista, fila, estado, alCerrar }: { vista: Vista<T>; fila: T; estado?: EstadoConfig; alCerrar: () => void }) {
  const navegar = useNavigate();
  const catalogos = useCatalogos().data;
  const enlace = vista.enlace(fila, estado);
  return (
    <Tarjeta className="resaltada" aria-label={`Detalle de ${vista.singular.toLowerCase()} ${fila.id_externo}`}>
      <div className="tarjeta-cab" style={{ padding: "14px 18px" }}>
        <div className="fila" style={{ gap: 10 }}>
          <Icono nombre={vista.icono} tamano={22} />
          <h2>{vista.singular} {fila.id_externo}</h2>
          <span className="mono cap">{formatoFechaHora(fila.inicio)} · {fila.cuenta}</span>
        </div>
        <div className="fila">
          {enlace && <BotonEnlace a={enlace.url} externo icono="open_in_new" chico>{enlace.texto}</BotonEnlace>}
          {fila.cliente_id !== null && (
            <Boton chico icono="history" onClick={() => navegar(`/historial?cliente=${fila.cliente_id}`)}>Ver historial del cliente</Boton>
          )}
          <Boton chico icono="close" aria-label="Cerrar el detalle" onClick={alCerrar} />
        </div>
      </div>
      <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--borde)", background: "var(--fondo-suave)" }}>
        <FranjaAsesor asesor={fila.asesor} asignacion={fila.asignacion} motivo={fila.motivo} />
      </div>
      <div className="detalle-columnas" style={{ padding: 18 }}>
        <div style={{ minWidth: 0 }}>
          {vista.tipo === "llamada"
            ? <PanelLlamada llamadaId={fila.id} retencionDias={estado?.retencion_audio_dias ?? 90} />
            : <Chat conversacionId={fila.id} />}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <div className="tarjeta p">
            <b>Datos</b>
            <dl className="datos" style={{ marginTop: 10 }}>
              {vista.datos(fila).map(([k, v]) => (<Fragment key={k}><dt>{k}</dt><dd>{v || "—"}</dd></Fragment>))}
            </dl>
          </div>
          <div className="tarjeta p">
            <EditorAsignacion tipo={vista.tipo} id={fila.id} personaId={fila.persona_id} asignacion={fila.asignacion} personas={catalogos?.personas ?? []} />
          </div>
        </div>
      </div>
    </Tarjeta>
  );
}

function Lote({ filas }: { filas: FilaLlamada[] }) {
  const avisar = useAvisos();
  const cliente = useQueryClient();
  const [abierto, setAbierto] = useState(false);
  const [confirmado, setConfirmado] = useState(false);
  const candidatas = filas.filter((f) => f.grabada && !f.transcripcion_estado && !["sin_grabacion", "vencido"].includes(f.audio_estado ?? "")).map((f) => f.id);
  const costo = useQuery({
    queryKey: ["lote", candidatas],
    queryFn: () => api.post<CostoLote>("/api/transcripcion/lote/costo", { ids: candidatas }),
    enabled: abierto && candidatas.length > 0,
    retry: false,
  });
  const encolar = useMutation({
    mutationFn: () => api.post<{ encoladas: number; costo_usd: number | null }>("/api/transcripcion/lote", { ids: candidatas, confirmado }),
    onSuccess: (r) => {
      avisar(`${entero(r.encoladas)} llamadas agregadas a la cola. Costo estimado: ${usd(r.costo_usd)}. Puede seguir trabajando.`);
      setConfirmado(false);
      cliente.invalidateQueries({ queryKey: ["inicio"] });
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const c = costo.data;
  return (
    <details className="tarjeta" open={abierto} onToggle={(e) => setAbierto((e.target as HTMLDetailsElement).open)}>
      <summary style={{ padding: "12px 16px", cursor: "pointer", fontWeight: 600, display: "flex", gap: 10, alignItems: "center" }}>
        <Icono nombre="graphic_eq" /> Transcribir en lote <Insignia tono="cola">{entero(candidatas.length)} sin transcribir en este filtro</Insignia>
      </summary>
      <div style={{ padding: "4px 16px 16px" }}>
        {candidatas.length === 0 ? <p className="cap">Todas las llamadas del listado ya están transcritas o no tienen grabación.</p>
          : costo.isLoading ? <Cargando filas={2} />
          : costo.error ? <ErrorCarga error={costo.error} />
          : c && (
            <div className="grilla g4" style={{ alignItems: "end" }}>
              <div><div className="cap">Llamadas</div><div className="mono" style={{ fontSize: 20 }}>{entero(c.llamadas)}</div></div>
              <div><div className="cap">Minutos</div><div className="mono" style={{ fontSize: 20 }}>{numero(c.minutos, 0)}</div></div>
              <div><div className="cap">Costo estimado · {c.modelo}</div><div className="mono" style={{ fontSize: 20 }}>{usd(c.costo_usd)}</div></div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {c.requiere_confirmacion && (
                  <Marcador marcado={confirmado} alCambiar={setConfirmado}
                    etiqueta={`Confirmo el gasto (supera ${usd(c.umbral_usd)} por lote)`} />
                )}
                <Boton variante="primario" icono="queue" cargando={encolar.isPending}
                  disabled={c.requiere_confirmacion && !confirmado} onClick={() => encolar.mutate()}>
                  Agregar {entero(c.llamadas)} a la cola
                </Boton>
              </div>
            </div>
          )}
        <p className="cap" style={{ marginBottom: 0 }}>La sincronización las transcribe unas cuantas por ciclo. El avance se ve en Transcripción.</p>
      </div>
    </details>
  );
}
