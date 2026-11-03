// Historial del cliente: todas sus llamadas y chats, en orden.

import { useDeferredValue, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/cliente";
import type { Catalogos, ElementoHistorial, EstadoConfig, Historial as DatosHistorial, ResumenCliente } from "../api/tipos";
import { Aviso, BotonEnlace, Boton, Cabecera, Cargando, ErrorCarga, Icono, Insignia, Tarjeta } from "../componentes/basicos";
import { Marcador, Texto } from "../componentes/campos";
import { Tabla } from "../componentes/Tabla";
import { EditorAsignacion, FranjaAsesor, origenAsignacion } from "../componentes/asignacion";
import { PanelLlamada } from "../componentes/Llamada";
import { Chat } from "../componentes/Chat";
import { entero, formatoFecha, formatoFechaHora, telefono } from "../utilidades/formato";

export default function Historial() {
  const [parametros, setParametros] = useSearchParams();
  const [texto, setTexto] = useState("");
  const [revisar, setRevisar] = useState(false);
  const buscado = useDeferredValue(texto);
  const clienteId = Number(parametros.get("cliente")) || null;
  const encontrados = useQuery({
    queryKey: ["clientes", buscado, revisar],
    queryFn: () => api.get<ResumenCliente[]>("/api/clientes", { q: buscado, revisar }),
  });

  return (
    <>
      <Cabecera titulo="Historial del cliente" subtitulo="Todas las llamadas y chats de un cliente, en orden" />
      <Tarjeta padding style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 420px" }}>
          <Texto etiqueta="Teléfono o nombre" type="search" value={texto} onChange={(e) => setTexto(e.target.value)}
            placeholder="612 345 678 · +34 612 345 678 · 0034612345678 · nombre" style={{ height: 42, fontSize: 16 }} />
        </div>
        <div style={{ height: 42, display: "flex", alignItems: "center" }}>
          <Marcador etiqueta="Teléfonos por revisar" marcado={revisar} alCambiar={setRevisar} />
        </div>
      </Tarjeta>

      {encontrados.isLoading ? <Cargando /> : encontrados.error ? <ErrorCarga error={encontrados.error} /> : (
        encontrados.data!.length === 0 ? <Aviso tipo="info">No encontramos a nadie con «{texto}». Revise el número o pruebe con el nombre.</Aviso> : (
          <Tarjeta>
            <div className="tarjeta-cab"><span className="cap">{texto ? `${entero(encontrados.data!.length)} coincidencias` : "Clientes con actividad más reciente"}</span></div>
            <Tabla filas={encontrados.data!} clave={(c) => c.id} alto={240} elegida={clienteId}
              alElegir={(c) => setParametros({ cliente: String(c.id) })}
              columnas={[
                { titulo: "Cliente", celda: (c) => <b>{c.nombre || "Sin nombre"}</b> },
                { titulo: "Teléfono", celda: (c) => <span className="fila mono" style={{ gap: 6 }}>{telefono(c.telefono)}{c.revisar && <Insignia tono="sin">Por revisar</Insignia>}</span> },
                { titulo: "Llamadas", celda: (c) => entero(c.llamadas), derecha: true },
                { titulo: "Chats", celda: (c) => entero(c.conversaciones), derecha: true },
                { titulo: "Última", celda: (c) => <span className="mono">{formatoFecha(c.ultima)}</span> },
              ]} />
          </Tarjeta>
        )
      )}
      {clienteId && <Cliente id={clienteId} />}
    </>
  );
}

function Cliente({ id }: { id: number }) {
  const [elegido, setElegido] = useState<string | null>(null);
  useEffect(() => setElegido(null), [id]);
  const consulta = useQuery({ queryKey: ["historial", id], queryFn: () => api.get<DatosHistorial>(`/api/clientes/${id}`) });
  if (consulta.isLoading) return <Cargando filas={4} texto="Juntando llamadas y chats…" />;
  if (consulta.error || !consulta.data) return <ErrorCarga error={consulta.error} />;
  const { cliente, elementos, por_asesor } = consulta.data;
  const maximo = Math.max(1, ...Object.values(por_asesor));
  const clave = (e: ElementoHistorial) => `${e.tipo}-${e.id}`;
  const actual = elementos.find((e) => clave(e) === elegido);
  return (
    <>
      {cliente.revisar && <Aviso tipo="atencion">El teléfono «{cliente.telefono}» no se pudo interpretar como un número válido. Puede que otras interacciones del mismo cliente estén con otro formato.</Aviso>}
      <Tarjeta padding style={{ display: "grid", gridTemplateColumns: "minmax(0,1.3fr) repeat(3, minmax(0,1fr)) minmax(0,1.6fr)", gap: 18 }}>
        <div><h2>{cliente.nombre || "Sin nombre"}</h2><div className="mono">{telefono(cliente.telefono)}</div></div>
        <div><div className="cap">Llamadas</div><div className="mono" style={{ fontSize: 24 }}>{entero(cliente.llamadas)}</div></div>
        <div><div className="cap">Chats</div><div className="mono" style={{ fontSize: 24 }}>{entero(cliente.conversaciones)}</div></div>
        <div><div className="cap">Última interacción</div><div className="mono" style={{ fontSize: 15, marginTop: 6 }}>{formatoFechaHora(cliente.ultima)}</div></div>
        <div>
          <div className="cap" style={{ marginBottom: 4 }}>Lo atendieron</div>
          {Object.entries(por_asesor).map(([asesor, n]) => (
            <div key={asesor} style={{ display: "grid", gridTemplateColumns: "120px minmax(0,1fr) 28px", gap: 8, alignItems: "center", fontSize: 13 }}>
              <span>{asesor}</span>
              <span style={{ height: 8, borderRadius: 4, background: "var(--borde)" }}><span style={{ display: "block", height: 8, borderRadius: 4, background: "#3e93c1", width: `${(n / maximo) * 100}%` }} /></span>
              <span className="mono" style={{ textAlign: "right" }}>{n}</span>
            </div>
          ))}
        </div>
      </Tarjeta>
      <Tarjeta>
        <div className="tarjeta-cab"><b>Línea de tiempo</b><span className="cap">Elija una fila para escucharla o leerla</span></div>
        <Tabla filas={elementos} clave={clave} elegida={elegido} alElegir={(e) => setElegido(clave(e) === elegido ? null : clave(e))} alto={420}
          columnas={[
            { titulo: "Tipo", celda: (e) => <span className="fila" style={{ gap: 4 }}><Icono nombre={e.tipo === "llamada" ? "call" : "chat"} tamano={18} />{e.tipo === "llamada" ? "Llamada" : "Chat"}</span> },
            { titulo: "Fecha", celda: (e) => <span className="mono">{formatoFechaHora(e.inicio)}</span> },
            { titulo: "Asesor", celda: (e) => <b>{e.asesor || "Sin asignar"}</b> },
            { titulo: "Asignación", celda: (e) => { const o = origenAsignacion(e.asesor, e.asignacion); return <Insignia tono={o.tono}>{o.texto}</Insignia>; } },
            { titulo: "Detalle", celda: (e) => e.resumen, ajusta: true },
            { titulo: "Cuenta", celda: (e) => e.cuenta },
          ]} />
      </Tarjeta>
      {actual && <DetalleElemento elemento={actual} alCerrar={() => setElegido(null)} />}
    </>
  );
}

function DetalleElemento({ elemento, alCerrar }: { elemento: ElementoHistorial; alCerrar: () => void }) {
  const estado = useQuery({ queryKey: ["estado"], queryFn: () => api.get<EstadoConfig>("/api/estado") }).data;
  const personas = useQuery({ queryKey: ["catalogos"], queryFn: () => api.get<Catalogos>("/api/catalogos") }).data?.personas ?? [];
  const enlace = elemento.tipo === "llamada" ? elemento.enlace_plataforma
    : estado?.chatwoot_conversacion?.replace("{id}", elemento.id_externo) ?? null;
  return (
    <Tarjeta className="resaltada">
      <div className="tarjeta-cab" style={{ padding: "14px 18px" }}>
        <div className="fila"><Icono nombre={elemento.tipo === "llamada" ? "call" : "chat"} tamano={22} /><h2>{elemento.tipo === "llamada" ? "Llamada" : "Chat"} del {formatoFechaHora(elemento.inicio)}</h2></div>
        <div className="fila">
          {enlace && <BotonEnlace a={enlace} externo chico icono="open_in_new">{elemento.tipo === "llamada" ? "Abrir en CloudTalk" : "Abrir en Chatwoot"}</BotonEnlace>}
          <Boton chico icono="close" aria-label="Cerrar el detalle" onClick={alCerrar} />
        </div>
      </div>
      <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--borde)", background: "var(--fondo-suave)" }}>
        <FranjaAsesor asesor={elemento.asesor} asignacion={elemento.asignacion} motivo={elemento.motivo} />
      </div>
      <div className="detalle-columnas" style={{ padding: 18 }}>
        <div style={{ minWidth: 0 }}>
          {elemento.tipo === "llamada" ? <PanelLlamada llamadaId={elemento.id} retencionDias={estado?.retencion_audio_dias ?? 90} /> : <Chat conversacionId={elemento.id} />}
        </div>
        <div className="tarjeta p">
          <EditorAsignacion tipo={elemento.tipo} id={elemento.id} personaId={elemento.persona_id} asignacion={elemento.asignacion} personas={personas} />
        </div>
      </div>
    </Tarjeta>
  );
}
