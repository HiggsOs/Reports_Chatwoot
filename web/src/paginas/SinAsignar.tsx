// Lo que ninguna regla pudo asignar, agrupado por motivo, para asignarlo de a
// una o en bloque.

import { useMemo, useState } from "react";
import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/cliente";
import type { FilaInteraccion, Listado, ResumenReasignacion, TipoInteraccion } from "../api/tipos";
import { Aviso, Boton, Cabecera, Cargando, ErrorCarga, Icono, Insignia, Tarjeta } from "../componentes/basicos";
import { Seleccion, Texto } from "../componentes/campos";
import { Tabla } from "../componentes/Tabla";
import { useCatalogos } from "../componentes/filtros";
import { useAvisos } from "../componentes/avisos";
import { diaIso, entero, formatoFechaHora, telefono } from "../utilidades/formato";

const TIPOS: { tipo: TipoInteraccion; titulo: string; plural: string; icono: string }[] = [
  { tipo: "llamada", titulo: "Llamadas", plural: "llamadas", icono: "call" },
  { tipo: "conversacion", titulo: "Conversaciones", plural: "chats", icono: "chat" },
];

export default function SinAsignar() {
  const [desde, setDesde] = useState(diaIso(new Date(), -30));
  const [hasta, setHasta] = useState(diaIso());
  const consultas = useQueries({
    queries: TIPOS.map(({ tipo }) => ({
      queryKey: ["interacciones", tipo, { desde, hasta, sin_asignar: true }],
      queryFn: () => api.get<Listado<FilaInteraccion>>(`/api/interacciones/${tipo}`, { desde, hasta, sin_asignar: true }),
    })),
  });
  const catalogos = useCatalogos();
  const personas = catalogos.data?.personas ?? [];
  const cargando = consultas.some((c) => c.isLoading);
  const error = consultas.find((c) => c.error)?.error;
  const total = consultas.reduce((n, c) => n + (c.data?.filas.length ?? 0), 0);

  const motivos = useMemo(() => {
    const conteo = new Map<string, { tipo: string; cuenta: string; motivo: string; cantidad: number }>();
    consultas.forEach((c, i) => c.data?.filas.forEach((f) => {
      const clave = `${i}|${f.cuenta}|${f.motivo}`;
      const actual = conteo.get(clave) ?? { tipo: TIPOS[i].plural, cuenta: f.cuenta, motivo: f.motivo || "Sin motivo", cantidad: 0 };
      actual.cantidad += 1;
      conteo.set(clave, actual);
    }));
    return [...conteo.values()].sort((a, b) => b.cantidad - a.cantidad);
  }, [consultas]);

  return (
    <>
      <Cabecera titulo="Sin asignar" subtitulo="Llamadas y chats que ninguna regla pudo asignar. Elija una o varias filas y asígnelas a un asesor." />
      <Tarjeta padding style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
        <div style={{ width: 170 }}><Texto etiqueta="Desde" type="date" value={desde} max={hasta} onChange={(e) => setDesde(e.target.value)} /></div>
        <div style={{ width: 170 }}><Texto etiqueta="Hasta" type="date" value={hasta} min={desde} onChange={(e) => setHasta(e.target.value)} /></div>
        <RevisarChats />
      </Tarjeta>

      {cargando ? <Cargando filas={5} texto="Buscando interacciones sin asesor…" />
        : error ? <ErrorCarga error={error} />
        : total === 0 ? <Aviso tipo="exito">No hay nada sin asignar en el rango. Las reglas cubren todas las cuentas.</Aviso>
        : (
          <>
            {personas.length === 0 && <Aviso tipo="atencion">Todavía no hay asesores. <Link to="/asesores">Créelos en Asesores</Link> para poder asignar.</Aviso>}
            <section>
              <h2 className="sec">Por qué están sin asignar</h2>
              <div className="grilla g3">
                {motivos.slice(0, 6).map((m) => (
                  <Tarjeta padding key={`${m.tipo}${m.cuenta}${m.motivo}`} style={m.cantidad === motivos[0].cantidad ? { borderColor: "var(--sin-borde)", background: "var(--aviso-fondo)" } : undefined}>
                    <div className="fila entre"><b className="mono" style={{ fontSize: 24, color: "var(--sin-texto)" }}>{entero(m.cantidad)}</b><span className="cap">{m.tipo}</span></div>
                    <div style={{ fontWeight: 600 }}>{m.cuenta}: {m.motivo}</div>
                    <Link to="/cuentas" className="cap" style={{ fontWeight: 600 }}>Revisar la regla de la cuenta <Icono nombre="arrow_forward" tamano={16} /></Link>
                  </Tarjeta>
                ))}
              </div>
            </section>
            {TIPOS.map(({ tipo, titulo, plural, icono }, i) => (
              <Bandeja key={tipo} tipo={tipo} titulo={titulo} plural={plural} icono={icono}
                filas={consultas[i].data?.filas ?? []} personas={personas.map((p) => ({ valor: p.id, texto: `${p.nombre || p.correo} · ${p.area}` }))} />
            ))}
          </>
        )}
    </>
  );
}

function Bandeja({ tipo, titulo, plural, icono, filas, personas }: {
  tipo: TipoInteraccion; titulo: string; plural: string; icono: string; filas: FilaInteraccion[]; personas: { valor: number; texto: string }[];
}) {
  const [elegidas, setElegidas] = useState<Set<string | number>>(new Set());
  const [persona, setPersona] = useState<number>(personas[0]?.valor ?? 0);
  const avisar = useAvisos();
  const cliente = useQueryClient();
  const asignar = useMutation({
    mutationFn: () => api.post<{ asignadas: number }>("/api/sin-asignar/asignar", { tipo, ids: [...elegidas], persona_id: persona || personas[0]?.valor }),
    onSuccess: (r) => {
      avisar(`${entero(r.asignadas)} ${plural} asignadas a ${personas.find((p) => p.valor === (persona || personas[0]?.valor))?.texto} (manual).`);
      setElegidas(new Set());
      cliente.invalidateQueries({ queryKey: ["interacciones"] });
      cliente.invalidateQueries({ queryKey: ["inicio"] });
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  return (
    <Tarjeta>
      <div className="tarjeta-cab" style={elegidas.size ? { background: "var(--fila-elegida)" } : undefined}>
        <h2 className="fila"><Icono nombre={icono} />{titulo} · {entero(filas.length)}</h2>
        {filas.length > 0 && personas.length > 0 && (
          <div className="fila" style={{ alignItems: "end" }}>
            <span className="cap"><b style={{ color: "var(--tinta)" }}>{entero(elegidas.size)} elegidas</b></span>
            <div style={{ width: 240 }}><Seleccion etiqueta="Asignar a" valor={persona || personas[0].valor} opciones={personas} alCambiar={setPersona} /></div>
            <Boton variante="primario" icono="person_add" disabled={!elegidas.size} cargando={asignar.isPending} onClick={() => asignar.mutate()}>
              Asignar {elegidas.size || ""}
            </Boton>
          </div>
        )}
      </div>
      <Tabla filas={filas} clave={(f) => f.id} alto={420} vacio={`No hay ${plural} sin asignar en el rango.`}
        seleccionMultiple={{ elegidas, alCambiar: setElegidas }}
        columnas={[
          { titulo: "Fecha", celda: (f) => <span className="mono">{formatoFechaHora(f.inicio)}</span> },
          { titulo: "Cuenta", celda: (f) => f.cuenta },
          { titulo: "Motivo", celda: (f) => <Insignia tono="sin">{f.motivo || "Sin motivo"}</Insignia> },
          { titulo: "Cliente", celda: (f) => f.cliente },
          { titulo: "Teléfono", celda: (f) => <span className="mono">{telefono(f.telefono)}</span> },
        ]} />
    </Tarjeta>
  );
}

// Vuelve a mirar todos los chats sin asesor: el que más mensajes envió, por su
// regla o por su correo. Útil tras cargar asesores o reglas.
function RevisarChats() {
  const avisar = useAvisos();
  const cliente = useQueryClient();
  const revisar = useMutation({
    mutationFn: () => api.post<ResumenReasignacion>("/api/sin-asignar/revisar"),
    onSuccess: (r) => {
      const asignadas = Object.entries(r.por_persona).filter(([p]) => p !== "Sin asignar");
      avisar(r.cambiaron
        ? `Se asignaron ${entero(r.cambiaron)} de ${entero(r.revisadas)} chats sin asesor: ${asignadas.map(([p, n]) => `${p}: ${entero(n)}`).join(" · ")}.`
        : `Se revisaron ${entero(r.revisadas)} chats sin asesor: ninguno se pudo asignar. Mire el motivo de cada uno.`);
      ["interacciones", "inicio", "cuentas"].forEach((k) => cliente.invalidateQueries({ queryKey: [k] }));
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  return (
    <div style={{ marginLeft: "auto", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
      <Boton icono="manage_search" cargando={revisar.isPending} onClick={() => revisar.mutate()}>Revisar de nuevo los chats sin asignar</Boton>
      <span className="cap">Los asigna al asesor que más mensajes envió (todas las fechas).</span>
    </div>
  );
}
