// Transcripción: configuración (claves, modelos y precios, límites), cola,
// gasto y precio real cobrado, y comparación de versiones.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/cliente";
import type {
  CobrosTraidos, ConfiguracionTranscripcion, FilaGasto, TrabajoConError, LlamadaComparable, ModeloDisponible, ModeloTranscripcion, Prueba, ResumenTranscripcion,
  TranscripcionesLlamada,
} from "../api/tipos";
import { Aviso, Boton, Cabecera, Cargando, ErrorCarga, Insignia, Metrica, Tarjeta } from "../componentes/basicos";
import { Seleccion, SelectorMultiple, Texto } from "../componentes/campos";
import { Pestanas } from "../componentes/Pestanas";
import { Tabla } from "../componentes/Tabla";
import { useAvisos } from "../componentes/avisos";
import { duracion, entero, formatoFechaHora, numero, usd } from "../utilidades/formato";

type IdPestana = "configuracion" | "cola" | "gasto" | "comparar";

export default function Transcripcion() {
  const resumen = useQuery({
    queryKey: ["transcripcion-resumen"],
    queryFn: () => api.get<ResumenTranscripcion>("/api/transcripcion/resumen"),
    // Con pedidos en curso, la cola se actualiza sola.
    refetchInterval: (q) => ((q.state.data?.abiertos.length ?? 0) > 0 ? 5000 : false),
  });
  const errores = resumen.data?.cola.error ?? 0;
  // Los totales salen de la cola entera: la tabla muestra solo las primeras filas.
  const abiertos = (resumen.data?.cola.pendiente ?? 0) + (resumen.data?.cola.en_proceso ?? 0);
  const [pestana, setPestana] = useState<IdPestana>(errores || abiertos ? "cola" : "configuracion");
  const r = resumen.data;
  const tope = r?.tope_mensual_usd;

  return (
    <>
      <Cabecera titulo="Transcripción" subtitulo="Proveedores, modelos y precios, la cola de trabajo y lo que cuesta de verdad." />
      {resumen.isLoading ? <Cargando /> : resumen.error ? <ErrorCarga error={resumen.error} /> : r && (
        <>
          <div className="grilla g4">
            <Metrica titulo="En cola" valor={entero(r.cola.pendiente ?? 0)} />
            <Metrica titulo="En proceso" valor={entero(r.cola.en_proceso ?? 0)} />
            <Metrica titulo="Con error" valor={entero(r.cola.error ?? 0)} tonoDetalle="mal" detalle={errores ? "Ver y reintentar en Cola" : undefined} />
            <Metrica titulo="Gasto del mes (estimado)" valor={usd(r.gasto_mes_usd)}
              detalle={tope ? `${numero((r.gasto_mes_usd / tope) * 100, 0)} % del tope de ${usd(tope)}` : "Sin tope mensual"} />
          </div>
          {r.procesador?.diagnostico && <Aviso tipo="error">{r.procesador.diagnostico}</Aviso>}
          {!r.configurada && <Aviso tipo="atencion">La transcripción no está configurada: elija el modelo principal y cargue la clave del proveedor en Configuración. También hace falta CloudTalk en <Link to="/general">General</Link>.</Aviso>}
          {tope && r.gasto_mes_usd >= tope && <Aviso tipo="error">Se alcanzó el tope mensual de {usd(tope)}: la cola está en pausa hasta el mes que viene o hasta subir el tope.</Aviso>}
          {tope && r.gasto_mes_usd < tope && r.gasto_mes_usd >= (tope * r.aviso_porcentaje) / 100 && <Aviso tipo="atencion">El gasto del mes ya pasó el {r.aviso_porcentaje} % del tope.</Aviso>}
        </>
      )}
      <Pestanas activa={pestana} alCambiar={setPestana} pestanas={[
        { id: "configuracion", titulo: "Configuración", icono: "tune" },
        { id: "cola", titulo: "Cola", icono: "queue", contador: errores + abiertos },
        { id: "gasto", titulo: "Gasto y precio real", icono: "payments" },
        { id: "comparar", titulo: "Comparar versiones", icono: "compare_arrows" },
      ]} />
      {pestana === "configuracion" && <Configuracion />}
      {pestana === "cola" && r && <Cola resumen={r} />}
      {pestana === "gasto" && <Gasto />}
      {pestana === "comparar" && <Comparar />}
    </>
  );
}

// --- Cola -----------------------------------------------------------------

// Cómo se elige el modelo al reintentar: el del pedido, el principal con sus
// respaldos, o uno en particular («deepgram:nova-3»).
const MISMO_MODELO = "";
const CONFIGURADOS = "__configurados";

function cuerpoReintento(eleccion: string) {
  if (eleccion === MISMO_MODELO) return { cambiar_modelo: false };
  return { cambiar_modelo: true, proveedor: eleccion === CONFIGURADOS ? null : eleccion };
}

function Cola({ resumen }: { resumen: ResumenTranscripcion }) {
  const avisar = useAvisos();
  const cliente = useQueryClient();
  const [conModelo, setConModelo] = useState(MISMO_MODELO);
  const nombreModelo = (clave: string | null) => (clave ? resumen.modelos.find((m) => m.clave === clave)?.titulo ?? clave.replace(":", " · ") : "Principal y respaldo");
  const opciones = [
    { valor: CONFIGURADOS, texto: "El principal y sus respaldos" },
    ...resumen.modelos.map((m) => ({ valor: m.clave, texto: `${m.titulo} · ${m.devuelve}` })),
  ];
  const reintentar = useMutation({
    mutationFn: () => api.post<{ encoladas: number }>("/api/transcripcion/reintentar", cuerpoReintento(conModelo)),
    onSuccess: (r) => { avisar(`${entero(r.encoladas)} llamadas se vuelven a transcribir ahora.`); cliente.invalidateQueries(); },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const reintentarUno = useMutation({
    mutationFn: ({ id, eleccion }: { id: number; eleccion: string }) => api.post(`/api/transcripcion/trabajos/${id}/reintentar`, cuerpoReintento(eleccion)),
    onSuccess: (_r, { eleccion }) => {
      avisar(eleccion === MISMO_MODELO ? "Se vuelve a transcribir ahora." : `Se vuelve a transcribir ahora con ${eleccion === CONFIGURADOS ? "el principal y sus respaldos" : nombreModelo(eleccion)}.`);
      cliente.invalidateQueries();
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const procesar = useMutation({
    mutationFn: () => api.post<{ pendientes: number }>("/api/transcripcion/procesar"),
    onSuccess: (r) => { avisar(`Se están transcribiendo ${entero(r.pendientes)} llamadas desde el panel. El avance se ve aquí.`); cliente.invalidateQueries(); },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const p = resumen.procesador;
  const esperando = resumen.cola.pendiente ?? 0;
  const accion = (e: TrabajoConError & { estado?: string }) => e.estado === "en_proceso" ? <span className="cap">—</span> : (
    <select className="entrada chica" aria-label={`Reintentar la llamada ${e.llamada}`} value="" disabled={!resumen.configurada || reintentarUno.isPending}
      onChange={(ev) => ev.target.value && reintentarUno.mutate({ id: e.id, eleccion: ev.target.value === "__mismo" ? MISMO_MODELO : ev.target.value })} style={{ minWidth: 190 }}>
      <option value="">Reintentar con…</option>
      <option value="__mismo">El mismo modelo ({nombreModelo(e.modelo)})</option>
      {opciones.map((o) => <option key={o.valor} value={o.valor}>{o.texto}</option>)}
    </select>
  );
  const columnaModelo = { titulo: "Modelo", celda: (e: TrabajoConError) => <span className="cap">{nombreModelo(e.modelo)}</span> };
  return (
    <>
      <p className="cap" style={{ margin: 0 }}>
        La sincronización transcribe hasta {resumen.por_ciclo} por ciclo, cada {resumen.intervalo_minutos} minutos. Si el modelo de un pedido falla, se prueban el principal y los de respaldo; si fallan todos, se reintenta tres veces y después queda en Errores. Hechas en total: {entero(resumen.cola.hecho ?? 0)}.
        {resumen.auto_min_segundos > 0 && ` Las llamadas grabadas nuevas de ${resumen.auto_min_segundos} s o más se agregan solas a la cola.`}
      </p>
      <Tarjeta>
        <div className="tarjeta-cab" style={{ flexWrap: "wrap", gap: 12 }}>
          <div>
            <b>Quién transcribe la cola</b>
            <p className="cap" style={{ margin: "4px 0 0" }}>
              Última vuelta de la sincronización por la cola: {p?.ultima_vuelta ? formatoFechaHora(p.ultima_vuelta) : "nunca"}
              {p?.resumen && typeof p.resumen.hechos === "number" && ` (${entero(p.resumen.hechos as number)} hechas)`}
              {" · "}último ciclo de la sincronización: {p?.sincronizacion ? formatoFechaHora(p.sincronizacion) : "nunca"}
              {resumen.procesando_en_panel && " · transcribiendo ahora desde el panel"}
            </p>
          </div>
          <Boton variante={p?.diagnostico ? "primario" : undefined} icono="play_arrow" cargando={procesar.isPending || resumen.procesando_en_panel}
            disabled={!resumen.configurada || esperando === 0} onClick={() => procesar.mutate()}>
            Transcribir la cola ahora ({entero(esperando)})
          </Boton>
        </div>
      </Tarjeta>
      {resumen.abiertos.length === 0 ? <Aviso tipo="info">No hay llamadas esperando transcripción.</Aviso> : (
        <Tarjeta>
          <div className="tarjeta-cab">
            <b>En cola · {entero(esperando + (resumen.cola.en_proceso ?? 0))}</b>
            {resumen.abiertos.length < esperando + (resumen.cola.en_proceso ?? 0) && <span className="cap">Se muestran las primeras {entero(resumen.abiertos.length)}, en el orden en que se van a transcribir.</span>}
          </div>
          <Tabla filas={resumen.abiertos} clave={(e) => e.id} alto="auto" columnas={[
            { titulo: "Llamada", celda: (e) => <span className="mono">{e.llamada}</span> },
            { titulo: "Fecha", celda: (e) => <span className="mono">{formatoFechaHora(e.inicio)}</span> },
            { titulo: "Estado", celda: (e) => <Insignia tono={e.estado === "en_proceso" ? "cola" : "neutro"}>{e.estado === "en_proceso" ? "Transcribiendo" : "Esperando"}</Insignia> },
            columnaModelo,
            { titulo: "Intentos", celda: (e) => e.intentos, derecha: true },
            { titulo: "Último error", celda: (e) => e.error ? <span style={{ color: "var(--error-texto)" }}>{e.error}</span> : <span className="cap">—</span>, ajusta: true },
            { titulo: "", celda: accion },
          ]} />
        </Tarjeta>
      )}
      {resumen.errores.length === 0 ? <Aviso tipo="exito">No hay transcripciones con error.</Aviso> : (
        <Tarjeta>
          <div className="tarjeta-cab" style={{ flexWrap: "wrap", gap: 12 }}>
            <b>Errores · {entero(resumen.errores.length)}</b>
            <div className="fila" style={{ gap: 8, alignItems: "flex-end" }}>
              <div style={{ width: 300 }}>
                <Seleccion etiqueta="Reintentar con" valor={conModelo} alCambiar={setConModelo}
                  opciones={[{ valor: MISMO_MODELO, texto: "El modelo de cada pedido" }, ...opciones]} />
              </div>
              <Boton variante="primario" icono="refresh" cargando={reintentar.isPending} disabled={!resumen.configurada} onClick={() => reintentar.mutate()}>
                Reintentar las que fallaron ({entero(resumen.errores.length)})
              </Boton>
            </div>
          </div>
          <Tabla filas={resumen.errores} clave={(e) => e.id} alto="auto" columnas={[
            { titulo: "Llamada", celda: (e) => <span className="mono">{e.llamada}</span> },
            { titulo: "Fecha", celda: (e) => <span className="mono">{formatoFechaHora(e.inicio)}</span> },
            columnaModelo,
            { titulo: "Intentos", celda: (e) => e.intentos, derecha: true },
            { titulo: "Error", celda: (e) => <span style={{ color: "var(--error-texto)" }}>{e.error}</span>, ajusta: true },
            { titulo: "", celda: accion },
          ]} />
        </Tarjeta>
      )}
    </>
  );
}

// --- Gasto y precio real ----------------------------------------------------

function meses(cantidad = 12): { valor: string; texto: string }[] {
  const hoy = new Date();
  return Array.from({ length: cantidad }, (_, i) => {
    const d = new Date(hoy.getFullYear(), hoy.getMonth() - i, 1);
    const valor = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
    return { valor, texto: d.toLocaleDateString("es-ES", { month: "long", year: "numeric" }) };
  });
}

function Gasto() {
  const opciones = useMemo(() => meses(), []);
  const [mes, setMes] = useState(opciones[0].valor);
  const filas = useQuery({ queryKey: ["gasto", mes], queryFn: () => api.get<FilaGasto[]>("/api/transcripcion/gasto", { mes }) });
  const configuracion = useQuery({ queryKey: ["transcripcion-configuracion"], queryFn: () => api.get<ConfiguracionTranscripcion>("/api/transcripcion/configuracion") });
  const textoMes = opciones.find((o) => o.valor === mes)?.texto;
  const modelos = useMemo(() => {
    const todos = new Map<string, { proveedor: string; modelo: string; titulo: string }>();
    (configuracion.data?.modelos ?? []).forEach((m) => todos.set(`${m.proveedor}:${m.modelo}`, { proveedor: m.proveedor, modelo: m.modelo, titulo: `${m.proveedor} · ${m.modelo}` }));
    (filas.data ?? []).forEach((f) => todos.set(`${f.proveedor}:${f.modelo}`, { proveedor: f.proveedor, modelo: f.modelo, titulo: f.titulo }));
    return [...todos.values()];
  }, [configuracion.data, filas.data]);
  const avisar = useAvisos();
  const cliente = useQueryClient();
  const configurados = new Set((configuracion.data?.modelos ?? []).map((m) => `${m.proveedor}:${m.modelo}`));
  const traer = useMutation({
    mutationFn: () => api.post<CobrosTraidos[]>("/api/transcripcion/cobros/traer", { mes }),
    onSuccess: () => cliente.invalidateQueries({ queryKey: ["gasto"] }),
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const usarPrecio = useMutation({
    mutationFn: (datos: { proveedor: string; modelo: string; precio_minuto: number }) => api.put("/api/transcripcion/modelos/precio", datos),
    onSuccess: (_r, datos) => {
      avisar(`Precio de ${datos.proveedor} · ${datos.modelo} actualizado a ${numero(datos.precio_minuto, 5)} USD/min.`);
      cliente.invalidateQueries({ queryKey: ["gasto"] });
      cliente.invalidateQueries({ queryKey: ["transcripcion-configuracion"] });
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  useEffect(() => traer.reset(), [mes]); // eslint-disable-line react-hooks/exhaustive-deps
  const diferencia = (f: FilaGasto) => (f.diferencia === null ? "—" : `${f.diferencia > 0 ? "+" : ""}${numero(f.diferencia * 100, 1)} %`);

  return (
    <>
      <div style={{ width: 240 }}><Seleccion etiqueta="Período" valor={mes} opciones={opciones} alCambiar={setMes} /></div>
      {filas.isLoading ? <Cargando /> : filas.error ? <ErrorCarga error={filas.error} /> : (
        <>
          <Tarjeta>
            <div className="tarjeta-cab"><b>Gasto de {textoMes}</b><span className="cap">Estimado por el panel con el precio configurado al transcribir</span></div>
            <Tabla filas={filas.data!} clave={(f) => `${f.proveedor}:${f.modelo}`} alto="auto" vacio="No hay transcripciones ni cobros cargados en ese mes." columnas={[
              { titulo: "Modelo", celda: (f) => <span className="mono">{f.titulo}</span> },
              { titulo: "Minutos", celda: (f) => <span className="mono">{numero(f.minutos_panel, 1)}</span>, derecha: true },
              { titulo: "USD estimados", celda: (f) => <span className="mono">{numero(f.usd_estimado, 2)}</span>, derecha: true },
            ]} />
          </Tarjeta>
          <Tarjeta>
            <div className="tarjeta-cab">
              <div><b>Precio real cobrado</b><br /><span className="cap">Tráigalo del proveedor (hoy Deepgram) o cárguelo abajo con lo que dice la factura. Más de un 5 % de diferencia se marca como desviado.</span></div>
              <Boton icono="download" cargando={traer.isPending} onClick={() => traer.mutate()}>Traer lo cobrado en {textoMes}</Boton>
            </div>
            {traer.data?.map((r) => (
              <div key={r.proveedor} style={{ padding: "0 14px 10px" }}>
                <Aviso tipo={r.ok ? "exito" : "error"}><b>{r.titulo}:</b> {r.mensaje}</Aviso>
              </div>
            ))}
            <Tabla filas={filas.data!} clave={(f) => `${f.proveedor}:${f.modelo}`} alto="auto" vacio="Sin datos en ese mes." columnas={[
              { titulo: "Modelo", celda: (f) => <span className="mono">{f.titulo}</span> },
              { titulo: "Min cobrados", celda: (f) => <span className="mono">{numero(f.minutos_cobrados, 0)}</span>, derecha: true },
              { titulo: "Min según el panel", celda: (f) => <span className="mono">{numero(f.minutos_panel, 0)}</span>, derecha: true },
              { titulo: "USD cobrados", celda: (f) => <span className="mono">{numero(f.usd_cobrados, 2)}</span>, derecha: true },
              { titulo: "USD/min real", celda: (f) => <span className="mono">{numero(f.precio_real, 4)}</span>, derecha: true },
              { titulo: "USD/min configurado", celda: (f) => <span className="mono">{numero(f.precio_configurado, 4)}</span>, derecha: true },
              { titulo: "Diferencia", celda: (f) => (f.desviado ? <Insignia tono="desviado" icono="warning">{diferencia(f)}</Insignia> : <span className="mono">{diferencia(f)}</span>), derecha: true },
              { titulo: "", celda: (f) => (f.precio_real !== null && (f.desviado || f.precio_configurado === null) && configurados.has(`${f.proveedor}:${f.modelo}`)
                ? <Boton chico icono="price_check" cargando={usarPrecio.isPending && usarPrecio.variables?.modelo === f.modelo}
                    onClick={() => usarPrecio.mutate({ proveedor: f.proveedor, modelo: f.modelo, precio_minuto: f.precio_real! })}>Usar este precio</Boton>
                : null) },
            ]} />
            {filas.data!.filter((f) => f.desviado).map((f) => (
              <div key={f.titulo} style={{ padding: "0 14px 14px" }}>
                <Aviso tipo="atencion">{f.titulo} cobra {diferencia(f)} respecto de lo configurado. Use el precio real ({numero(f.precio_real, 4)} USD/min) o revise si el proveedor redondea cada audio al minuto.</Aviso>
              </div>
            ))}
          </Tarjeta>
          {modelos.length > 0 && <CargarCobro mes={mes} textoMes={textoMes ?? ""} modelos={modelos} />}
        </>
      )}
    </>
  );
}

function CargarCobro({ mes, textoMes, modelos }: { mes: string; textoMes: string; modelos: { proveedor: string; modelo: string; titulo: string }[] }) {
  const avisar = useAvisos();
  const cliente = useQueryClient();
  const [elegido, setElegido] = useState(`${modelos[0].proveedor}:${modelos[0].modelo}`);
  const [minutos, setMinutos] = useState("");
  const [importe, setImporte] = useState("");
  const guardar = useMutation({
    mutationFn: () => {
      const m = modelos.find((x) => `${x.proveedor}:${x.modelo}` === elegido)!;
      return api.put("/api/transcripcion/cobros", { mes, proveedor: m.proveedor, modelo: m.modelo, minutos: minutos.replace(",", "."), usd: importe.replace(",", ".") });
    },
    onSuccess: () => { avisar(`Cobro de ${textoMes} guardado.`); setMinutos(""); setImporte(""); cliente.invalidateQueries({ queryKey: ["gasto"] }); },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  return (
    <Tarjeta padding>
      <form onSubmit={(e) => { e.preventDefault(); guardar.mutate(); }} style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr) minmax(0,1fr) auto", gap: 12, alignItems: "end" }}>
        <Seleccion etiqueta={`Cargar lo cobrado en ${textoMes}`} valor={elegido} alCambiar={setElegido}
          opciones={modelos.map((m) => ({ valor: `${m.proveedor}:${m.modelo}`, texto: m.titulo }))} />
        <Texto etiqueta="Minutos cobrados" inputMode="decimal" value={minutos} onChange={(e) => setMinutos(e.target.value)} />
        <Texto etiqueta="USD cobrados" inputMode="decimal" value={importe} onChange={(e) => setImporte(e.target.value)} />
        <Boton type="submit" icono="save" disabled={!minutos || !importe} cargando={guardar.isPending}>Guardar el cobro</Boton>
      </form>
    </Tarjeta>
  );
}

// --- Comparar versiones ------------------------------------------------------

function Comparar() {
  const comparables = useQuery({ queryKey: ["comparables"], queryFn: () => api.get<LlamadaComparable[]>("/api/transcripcion/comparables") });
  const [llamada, setLlamada] = useState<number | null>(null);
  const elegida = llamada ?? comparables.data?.[0]?.llamada_id ?? null;
  const versiones = useQuery({
    queryKey: ["transcripciones", elegida],
    queryFn: () => api.get<TranscripcionesLlamada>(`/api/llamadas/${elegida}/transcripciones`),
    enabled: elegida !== null,
  });
  if (comparables.isLoading) return <Cargando />;
  if (comparables.error) return <ErrorCarga error={comparables.error} />;
  if (!comparables.data!.length) return <Aviso tipo="info">Cuando una llamada tenga dos transcripciones (con «Transcribir de nuevo» y otro modelo), aquí se ven lado a lado.</Aviso>;
  const [a, b] = versiones.data?.versiones ?? [];
  const textosB = new Set(b?.segmentos.map((s) => s.texto.trim()));
  return (
    <>
      <div style={{ maxWidth: 420 }}>
        <Seleccion etiqueta="Llamada" valor={elegida ?? 0} alCambiar={setLlamada}
          opciones={comparables.data!.map((c) => ({ valor: c.llamada_id, texto: `${c.llamada} · ${formatoFechaHora(c.inicio)} · ${c.transcripciones} versiones` }))} />
      </div>
      {versiones.isLoading ? <Cargando /> : (
        <div className="grilla g2">
          {[a, b].filter(Boolean).map((v) => (
            <Tarjeta padding key={v.id}>
              <div className="fila entre"><b className="mono">{v.modelo}</b>{v.principal && <Insignia tono="ok" icono="star">Principal</Insignia>}</div>
              <span className="cap">{formatoFechaHora(v.creado_en)} · {usd(v.costo_estimado === null ? null : Number(v.costo_estimado), 4)}</span>
              <div className="dialogo" style={{ marginTop: 8 }}>
                {v.segmentos.map((s, i) => (
                  <div key={i} className="linea" style={v === a && !textosB.has(s.texto.trim()) ? { background: "var(--aviso-fondo)" } : undefined}>
                    <span className="mono cap">{s.inicio !== null ? duracion(s.inicio) : ""}</span>
                    <b>{s.hablante === "agente" ? "Agente" : s.hablante === "cliente" ? "Cliente" : s.etiqueta ? `Hablante ${s.etiqueta}` : "—"}</b>
                    <span>{s.texto}</span>
                  </div>
                ))}
              </div>
            </Tarjeta>
          ))}
        </div>
      )}
    </>
  );
}

// --- Configuración -------------------------------------------------------------

const AUTOMATICA = [
  { valor: 0, texto: "No: solo a mano o en lote" },
  { valor: 30, texto: "Sí, las de 30 s o más" },
  { valor: 60, texto: "Sí, las de 60 s o más" },
  { valor: 1, texto: "Sí, todas" },
];

function Configuracion() {
  const consulta = useQuery({ queryKey: ["transcripcion-configuracion"], queryFn: () => api.get<ConfiguracionTranscripcion>("/api/transcripcion/configuracion") });
  if (consulta.isLoading) return <Cargando filas={6} />;
  if (consulta.error || !consulta.data) return <ErrorCarga error={consulta.error} />;
  return (
    <>
      <Claves configuracion={consulta.data} />
      <Modelos configuracion={consulta.data} />
    </>
  );
}

function Claves({ configuracion }: { configuracion: ConfiguracionTranscripcion }) {
  return (
    <section>
      <h2 style={{ marginBottom: 4 }}>Proveedores y claves de API</h2>
      <p className="cap" style={{ marginTop: 0 }}>Las claves se guardan cifradas y nunca se vuelven a mostrar completas. Si una clave también está en el entorno del servidor, manda la del panel.</p>
      <div className="grilla g3">{configuracion.proveedores.map((p) => <ClaveProveedor key={p.nombre} proveedor={p} />)}</div>
    </section>
  );
}

function ClaveProveedor({ proveedor }: { proveedor: ConfiguracionTranscripcion["proveedores"][number] }) {
  const avisar = useAvisos();
  const cliente = useQueryClient();
  const [clave, setClave] = useState("");
  const guardar = useMutation({
    mutationFn: (valor: string | null) => api.put(`/api/transcripcion/claves/${proveedor.nombre}`, { clave: valor }),
    onSuccess: (_r, valor) => { avisar(valor ? `Clave de ${proveedor.titulo} guardada.` : `Clave de ${proveedor.titulo} quitada del panel.`); setClave(""); cliente.invalidateQueries(); },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const probar = useMutation({ mutationFn: () => api.post<Prueba>(`/api/transcripcion/claves/${proveedor.nombre}/probar`, { clave: clave || null }) });
  const tiene = !!proveedor.clave_mascara;
  return (
    <Tarjeta padding style={{ display: "flex", flexDirection: "column", gap: 10, ...(tiene ? {} : { borderStyle: "dashed" }) }}>
      <div className="fila entre"><b style={{ fontSize: 16 }}>{proveedor.titulo}</b><Insignia tono={tiene ? "ok" : "sin"}>{tiene ? "Con clave" : "Sin clave"}</Insignia></div>
      <Texto etiqueta="Clave de API" type="password" autoComplete="off" value={clave} onChange={(e) => setClave(e.target.value)}
        placeholder={tiene ? `Guardada (${proveedor.origen_clave === "panel" ? "en el panel" : "en el entorno"}): ${proveedor.clave_mascara}` : "Pegue la clave"} />
      <div className="fila">
        <Boton variante="primario" icono="save" disabled={!clave.trim()} cargando={guardar.isPending} onClick={() => guardar.mutate(clave.trim())}>Guardar</Boton>
        <Boton icono="network_check" disabled={!tiene && !clave} cargando={probar.isPending} onClick={() => probar.mutate()}>Probar conexión</Boton>
        {proveedor.origen_clave === "panel" && <Boton chico variante="peligro" onClick={() => guardar.mutate(null)}>Quitar del panel</Boton>}
      </div>
      {probar.data && <Aviso tipo={probar.data.ok ? "exito" : "error"}>{probar.data.mensaje}</Aviso>}
    </Tarjeta>
  );
}

// `manual`: el id se escribe a mano (un modelo que el panel todavía no conoce).
function QueDevuelve({ texto }: { texto: string | undefined }) {
  if (!texto) return <span className="cap">Desconocido: se trata como solo texto</span>;
  const diariza = texto.startsWith("separa hablantes");
  return (
    <span className="fila" style={{ gap: 6, flexWrap: "wrap" }}>
      <Insignia tono={diariza ? "ok" : "neutro"} icono={diariza ? "record_voice_over" : undefined}>{diariza ? "Separa hablantes" : "No separa hablantes"}</Insignia>
      <span className="cap">{texto.includes("tiempos") ? "con tiempos" : "solo texto"}</span>
    </span>
  );
}

interface FilaModelo extends ModeloTranscripcion { precio: string; manual?: boolean }

const OTRO_MODELO = "__otro";

function Modelos({ configuracion }: { configuracion: ConfiguracionTranscripcion }) {
  const avisar = useAvisos();
  const cliente = useQueryClient();
  const iniciales = () => configuracion.modelos.map((m) => ({ ...m, precio: m.precio_minuto === null ? "" : String(m.precio_minuto).replace(".", ",") }));
  const [modelos, setModelos] = useState<FilaModelo[]>(iniciales);
  const [principal, setPrincipal] = useState(configuracion.principal ?? "");
  const [respaldo, setRespaldo] = useState<string[]>(configuracion.respaldo);
  const [idioma, setIdioma] = useState(configuracion.idioma);
  const [vocabulario, setVocabulario] = useState(configuracion.vocabulario.join(", "));
  const [frasesAgente, setFrasesAgente] = useState(configuracion.frases_agente.join(", "));
  const [canal, setCanal] = useState(configuracion.canal_agente);
  const [auto, setAuto] = useState(configuracion.auto_min_segundos);
  const [tope, setTope] = useState(configuracion.tope_mensual_usd ? String(configuracion.tope_mensual_usd) : "");
  const [aviso, setAviso] = useState(configuracion.aviso_porcentaje);
  const [confirmar, setConfirmar] = useState(configuracion.confirmar_lote_usd ? String(configuracion.confirmar_lote_usd) : "");
  useEffect(() => setModelos(iniciales()), [configuracion]); // eslint-disable-line react-hooks/exhaustive-deps

  // Lo que cada proveedor con clave ofrece hoy (su API de modelos), sumado a los conocidos.
  const conClave = configuracion.proveedores.filter((p) => p.clave_mascara);
  const disponibles = useQueries({
    queries: conClave.map((p) => ({
      queryKey: ["modelos-disponibles", p.nombre, configuracion.idioma],
      queryFn: () => api.get<ModeloDisponible[]>(`/api/transcripcion/proveedores/${p.nombre}/modelos`),
      staleTime: 10 * 60 * 1000,
      retry: false,
    })),
  });
  const conocidos: Record<string, Record<string, string>> = Object.fromEntries(configuracion.proveedores.map((p) => [p.nombre, { ...p.modelos_conocidos }]));
  conClave.forEach((p, i) => {
    for (const d of disponibles[i]?.data ?? []) conocidos[p.nombre][d.modelo] = d.devuelve;
  });
  const fallas = conClave.map((p, i) => ({ p, error: disponibles[i]?.error })).filter((f) => f.error);
  const primerModelo = (proveedor: string) => Object.keys(conocidos[proveedor] ?? {})[0] ?? "";
  const activos = modelos.filter((m) => m.activo && m.modelo.trim()).map((m) => `${m.proveedor}:${m.modelo.trim()}`);
  const titulo = (clave: string) => clave.replace(":", " · ");
  const cambiar = (i: number, cambios: Partial<FilaModelo>) => setModelos(modelos.map((m, j) => (j === i ? { ...m, ...cambios } : m)));
  const importe = (texto: string) => (texto.trim() ? Number(texto.replace(",", ".")) : null);

  const guardar = useMutation({
    mutationFn: () => api.put("/api/transcripcion/configuracion", {
      modelos: modelos.filter((m) => m.modelo.trim()).map((m) => ({
        proveedor: m.proveedor, modelo: m.modelo.trim(), redondeo: m.redondeo, activo: m.activo,
        precio_minuto: m.precio.trim() ? m.precio.trim().replace(",", ".") : null,
      })),
      principal: activos.includes(principal) ? principal : null,
      respaldo: respaldo.filter((r) => activos.includes(r) && r !== principal),
      idioma, vocabulario: vocabulario.split(",").map((v) => v.trim()).filter(Boolean),
      frases_agente: frasesAgente.split(",").map((v) => v.trim()).filter(Boolean), canal_agente: canal,
      auto_min_segundos: auto, tope_mensual_usd: importe(tope), aviso_porcentaje: aviso, confirmar_lote_usd: importe(confirmar),
    }),
    onSuccess: () => { avisar("Configuración de transcripción guardada. La cola la usa desde su próximo ciclo."); cliente.invalidateQueries(); },
    onError: (e) => avisar((e as Error).message, "error"),
  });

  return (
    <>
      <Tarjeta>
        <div className="tarjeta-cab">
          <div><h2>Modelos y precios</h2><span className="cap">La lista de modelos sale de cada proveedor con clave (los que sirven para el idioma configurado). Copie el precio de su tarifa (USD por minuto). Un modelo apagado no se ofrece, pero sus transcripciones viejas se siguen leyendo.</span></div>
          <Boton chico icono="add" onClick={() => {
            const proveedor = configuracion.proveedores[0]?.nombre ?? "openai";
            setModelos([...modelos, { proveedor, modelo: primerModelo(proveedor), precio_minuto: null, redondeo: "segundo", activo: true, precio: "" }]);
          }}>Agregar modelo</Boton>
        </div>
        {fallas.map(({ p, error }) => (
          <Aviso key={p.nombre} tipo="atencion">No se pudo traer la lista de modelos de {p.titulo} ({(error as Error).message}). Se muestran los conocidos.</Aviso>
        ))}
        <div className="tabla-caja">
          <table className="tabla">
            <thead><tr><th>Activo</th><th>Proveedor</th><th>Modelo</th><th>Qué devuelve</th><th className="derecha">USD / min</th><th>Mínimo cobrado</th><th className="derecha">Llamada de 5 min</th><th /></tr></thead>
            <tbody>
              {modelos.map((m, i) => {
                const precio = importe(m.precio);
                return (
                  <tr key={i} style={m.activo ? undefined : { opacity: 0.65 }}>
                    <td><input type="checkbox" aria-label={`Activar ${m.modelo || "modelo nuevo"}`} checked={m.activo} onChange={(e) => cambiar(i, { activo: e.target.checked })} /></td>
                    <td>
                      <select className="entrada chica" aria-label="Proveedor" value={m.proveedor} style={{ minWidth: 120 }}
                        onChange={(e) => cambiar(i, { proveedor: e.target.value, modelo: primerModelo(e.target.value), manual: false })}>
                        {configuracion.proveedores.map((p) => <option key={p.nombre} value={p.nombre}>{p.titulo}</option>)}
                      </select>
                    </td>
                    <td>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <select className="entrada chica mono" aria-label="Modelo" style={{ width: 260 }}
                          value={m.manual || (m.modelo.trim() && !conocidos[m.proveedor]?.[m.modelo.trim()]) ? OTRO_MODELO : m.modelo.trim()}
                          onChange={(e) => cambiar(i, e.target.value === OTRO_MODELO ? { modelo: "", manual: true } : { modelo: e.target.value, manual: false })}>
                          {!m.modelo.trim() && !m.manual && <option value="">Elija un modelo</option>}
                          {Object.keys(conocidos[m.proveedor] ?? {}).map((id) => <option key={id} value={id}>{id}</option>)}
                          <option value={OTRO_MODELO}>Otro (escribir el id)…</option>
                        </select>
                        {(m.manual || (m.modelo.trim() && !conocidos[m.proveedor]?.[m.modelo.trim()])) && (
                          <input className="entrada chica mono" aria-label="Id del modelo" placeholder="Id exacto del modelo" value={m.modelo}
                            onChange={(e) => cambiar(i, { modelo: e.target.value, manual: true })} style={{ width: 260 }} />
                        )}
                      </div>
                    </td>
                    <td><QueDevuelve texto={conocidos[m.proveedor]?.[m.modelo.trim()]} /></td>
                    <td className="derecha"><input className="entrada chica mono" aria-label={`USD por minuto de ${m.modelo}`} inputMode="decimal" value={m.precio} onChange={(e) => cambiar(i, { precio: e.target.value })} style={{ width: 90, textAlign: "right" }} placeholder="—" /></td>
                    <td>
                      <select className="entrada chica" aria-label="Mínimo cobrado" value={m.redondeo} onChange={(e) => cambiar(i, { redondeo: e.target.value as "segundo" | "minuto" })}>
                        <option value="segundo">Por segundo</option>
                        <option value="minuto">Redondea al minuto</option>
                      </select>
                    </td>
                    <td className="derecha mono">{precio === null || Number.isNaN(precio) ? "sin precio" : usd(precio * 5, 3)}</td>
                    <td><Boton chico icono="delete" aria-label={`Quitar ${m.modelo || "modelo"}`} onClick={() => setModelos(modelos.filter((_, j) => j !== i))} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Tarjeta>

      <Tarjeta padding style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <h2>Cómo se transcribe</h2>
        {activos.length === 0 && <Aviso tipo="atencion">Active al menos un modelo para poder elegir el principal.</Aviso>}
        <div className="grilla g2">
          <Seleccion etiqueta="Modelo principal" valor={activos.includes(principal) ? principal : ""} alCambiar={setPrincipal} ayuda="Solo aparecen los modelos activos."
            opciones={[{ valor: "", texto: "Elija un modelo" }, ...activos.map((c) => ({ valor: c, texto: titulo(c) }))]} />
          <SelectorMultiple etiqueta="Respaldo (si falla el principal)" vacio="Ninguno" elegidos={respaldo.filter((r) => activos.includes(r) && r !== principal)} alCambiar={setRespaldo}
            opciones={activos.filter((c) => c !== principal).map((c) => ({ valor: c, texto: titulo(c) }))} />
        </div>
        <div className="grilla g3">
          <Texto etiqueta="Idioma" value={idioma} onChange={(e) => setIdioma(e.target.value)} ayuda="Código ISO: es, en, pt…" />
          <Seleccion etiqueta="Canal del agente en grabaciones estéreo" valor={canal} alCambiar={setCanal}
            opciones={[{ valor: "izquierdo", texto: "Izquierdo (1)" }, { valor: "derecho", texto: "Derecho (2)" }]}
            ayuda="Con estéreo, cada canal es una persona." />
          <Seleccion etiqueta="Transcribir llamadas nuevas" valor={auto} alCambiar={setAuto}
            opciones={AUTOMATICA.some((a) => a.valor === auto) ? AUTOMATICA : [...AUTOMATICA, { valor: auto, texto: `Sí, las de ${auto} s o más` }]} />
        </div>
        <Texto etiqueta="Vocabulario (separado por comas)" value={vocabulario} onChange={(e) => setVocabulario(e.target.value)}
          ayuda="Nombres propios, marcas, productos: ayudan a escribirlos bien." />
        <Texto etiqueta="Frases del agente (separadas por comas)" value={frasesAgente} onChange={(e) => setFrasesAgente(e.target.value)}
          ayuda="Lo que dice el agente al atender («servicio de grúa», «grúa privada»…). Cuando el modelo separa las voces, la que dice estas frases queda como Agente. Sin importar acentos ni mayúsculas." />
      </Tarjeta>

      <Tarjeta padding style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <h2>Límites de gasto</h2>
        <div className="grilla g3">
          <Texto etiqueta="Tope mensual (USD)" inputMode="decimal" value={tope} onChange={(e) => setTope(e.target.value)} placeholder="Sin tope"
            ayuda="Al llegar, la cola se pausa hasta el mes siguiente." />
          <Seleccion etiqueta="Avisar en Inicio al llegar al" valor={aviso} alCambiar={setAviso}
            opciones={[50, 70, 80, 90].map((v) => ({ valor: v, texto: `${v} % del tope` }))} />
          <Texto etiqueta="Pedir confirmación en lotes de más de (USD)" inputMode="decimal" value={confirmar} onChange={(e) => setConfirmar(e.target.value)} placeholder="Nunca" />
        </div>
      </Tarjeta>

      <div className="tarjeta p fila entre" style={{ position: "sticky", bottom: 12, borderColor: "#71c0f4", boxShadow: "0 2px 10px rgba(11, 90, 142, .12)" }}>
        <span className="cap">Los cambios valen desde el próximo ciclo de la cola.</span>
        <Boton variante="primario" icono="save" cargando={guardar.isPending} onClick={() => guardar.mutate()}>Guardar la configuración de transcripción</Boton>
      </div>
    </>
  );
}
