// El chat de una conversación: burbujas del cliente y del asesor, notas
// internas resaltadas y actividades del sistema en gris.

import { useQuery } from "@tanstack/react-query";
import { api } from "../api/cliente";
import type { Mensaje } from "../api/tipos";
import { Aviso, Cargando, ErrorCarga, Insignia } from "./basicos";
import { formatoFechaHora, formatoHora } from "../utilidades/formato";

const iniciales = (nombre: string) =>
  nombre.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";

export function Chat({ conversacionId }: { conversacionId: number }) {
  const consulta = useQuery({
    queryKey: ["mensajes", conversacionId],
    queryFn: () => api.get<Mensaje[] | null>(`/api/conversaciones/${conversacionId}/mensajes`),
  });
  if (consulta.isLoading) return <Cargando texto="Trayendo mensajes…" />;
  if (consulta.error) return <ErrorCarga error={consulta.error} />;
  const mensajes = consulta.data;
  if (mensajes === null || mensajes === undefined)
    return <Aviso tipo="info">Los mensajes de este chat todavía no están guardados. Si es de los últimos días, llegan en el próximo ciclo de sincronización. Mientras tanto se pueden leer en Chatwoot.</Aviso>;
  if (mensajes.length === 0) return <p className="cap">El chat no tiene mensajes con texto.</p>;
  return (
    <div className="chat">
      {mensajes.map((m, i) => {
        if (m.rol === "actividad")
          return <div className="actividad" key={i}>{m.texto} · <span className="mono">{formatoHora(m.fecha)}</span></div>;
        return (
          <div key={i} className={`mensaje ${m.rol === "cliente" ? "cliente" : m.rol === "nota" ? "asesor nota" : "asesor"}`}>
            <span className="avatar" aria-hidden>{iniciales(m.autor)}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="fila" style={{ gap: 8 }}>
                <b style={{ fontSize: 13 }}>{m.autor}</b>
                <span className="mono cap" title={formatoFechaHora(m.fecha)}>{formatoHora(m.fecha)}</span>
                {m.rol === "nota" && <Insignia tono="sin">Nota interna · no la ve el cliente</Insignia>}
              </div>
              <div style={{ marginTop: 2, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{m.texto}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
