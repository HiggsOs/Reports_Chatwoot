// Cuentas de CloudTalk y Chatwoot y sus reglas de asignación: la regla
// vigente, su ocupación semanal, el historial y una regla nueva con vista
// previa obligatoria antes de guardar.

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/cliente";
import type { DetalleCuenta, EstadoConfig, Estrategia, FilaCuenta, ResumenReasignacion } from "../api/tipos";
import { Aviso, Boton, Cabecera, Cargando, ErrorCarga, Insignia, Tarjeta } from "../componentes/basicos";
import { Marcador, Texto } from "../componentes/campos";
import { Tabla } from "../componentes/Tabla";
import { useCatalogos } from "../componentes/filtros";
import { useAvisos } from "../componentes/avisos";
import { FORMULARIOS, completar, faltantes, type Parametros } from "../componentes/formulariosRegla";
import { diaIso, entero, formatoFecha } from "../utilidades/formato";

const PLATAFORMA: Record<string, string> = { cloudtalk: "CloudTalk", chatwoot: "Chatwoot" };
const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
// Colores de las personas en la ocupación: tonos claros de la paleta, con texto oscuro.
const COLORES = ["#a0d5f8", "#cabddb", "#e2d7b6", "#b2d4e6", "#d0eafb", "#e5deed"];

export default function Cuentas() {
  const cliente = useQueryClient();
  const avisar = useAvisos();
  const cuentas = useQuery({ queryKey: ["cuentas"], queryFn: () => api.get<FilaCuenta[]>("/api/cuentas") });
  const estado = useQuery({ queryKey: ["estado"], queryFn: () => api.get<EstadoConfig>("/api/estado") });
  const [elegida, setElegida] = useState<number | null>(null);
  const actualizar = useMutation({
    mutationFn: () => api.post<{ mensajes: string[]; errores: string[] }>("/api/cuentas/actualizar"),
    onSuccess: (r) => {
      r.mensajes.forEach((m) => avisar(m));
      r.errores.forEach((m) => avisar(m, "error"));
      cliente.invalidateQueries({ queryKey: ["cuentas"] });
      cliente.invalidateQueries({ queryKey: ["catalogos"] });
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const faltan = [estado.data && !estado.data.cloudtalk && "CloudTalk", estado.data && !estado.data.chatwoot && "Chatwoot"].filter(Boolean);

  return (
    <>
      <Cabecera titulo="Cuentas y reglas de asignación" subtitulo="Cada cuenta compartida necesita una regla que diga quién atendió según el día y la hora (hora de España).">
        <Boton icono="sync" cargando={actualizar.isPending} onClick={() => actualizar.mutate()}>Actualizar cuentas desde las plataformas</Boton>
      </Cabecera>
      {faltan.length > 0 && <Aviso tipo="info">{faltan.join(" y ")} no está conectado: sus cuentas no se pueden traer. <Link to="/general">Configurar las conexiones</Link></Aviso>}

      {cuentas.isLoading ? <Cargando /> : cuentas.error ? <ErrorCarga error={cuentas.error} /> : cuentas.data!.length === 0 ? (
        <Aviso tipo="info">Todavía no hay cuentas. Presione «Actualizar cuentas desde las plataformas».</Aviso>
      ) : (
        <Tarjeta>
          <div className="tarjeta-cab"><b>Cuentas · {entero(cuentas.data!.length)}</b><span className="cap">Primero las que no tienen regla. Elija una para ver o cambiar su regla.</span></div>
          <Tabla filas={cuentas.data!} clave={(c) => c.id} elegida={elegida} alElegir={(c) => setElegida(c.id)} alto={360}
            columnas={[
              { titulo: "Cuenta", celda: (c) => <b>{c.nombre}</b> },
              { titulo: "Origen", celda: (c) => PLATAFORMA[c.plataforma] ?? c.plataforma },
              { titulo: "Regla vigente", celda: (c) => <Insignia tono={c.estrategia ? "auto" : "sin"}>{c.estrategia ?? "Sin regla"}</Insignia> },
              { titulo: "Quién", celda: (c) => <span className="cap" style={{ color: "var(--etiqueta)" }}>{c.detalle.join(" · ") || c.aviso}</span>, ajusta: true },
              { titulo: "Desde", celda: (c) => <span className="mono">{c.estrategia ? (c.vigente_desde ? formatoFecha(c.vigente_desde) : "siempre") : "—"}</span> },
              { titulo: "Aviso", celda: (c) => (c.aviso && c.estrategia ? <Insignia tono="error">{c.aviso}</Insignia> : null) },
            ]} />
        </Tarjeta>
      )}
      {elegida && <Cuenta id={elegida} />}
    </>
  );
}

function Cuenta({ id }: { id: number }) {
  const detalle = useQuery({ queryKey: ["cuenta", id], queryFn: () => api.get<DetalleCuenta>(`/api/cuentas/${id}`) });
  if (detalle.isLoading) return <Cargando filas={4} />;
  if (detalle.error || !detalle.data) return <ErrorCarga error={detalle.error} />;
  const d = detalle.data;
  return (
    <>
      {d.estrategia && <Ocupacion horario={d.horario} nombre={d.nombre} />}
      {d.historial.length > 0 && (
        <Tarjeta>
          <div className="tarjeta-cab"><b>Historial de reglas · {d.nombre}</b></div>
          <Tabla filas={d.historial} clave={(r) => `${r.desde}-${r.estrategia}-${r.hasta}`} alto="auto"
            columnas={[
              { titulo: "Estrategia", celda: (r) => r.estrategia },
              { titulo: "Desde", celda: (r) => <span className="mono">{r.desde}</span> },
              { titulo: "Hasta", celda: (r) => r.hasta === "vigente" ? <Insignia tono="ok">Vigente</Insignia> : <span className="mono">{r.hasta}</span> },
              { titulo: "Detalle", celda: (r) => r.detalle.join(" · "), ajusta: true },
            ]} />
        </Tarjeta>
      )}
      <NuevaRegla cuenta={d} />
      {d.estrategia && <Recalcular cuenta={d} />}
    </>
  );
}

function Ocupacion({ horario, nombre }: { horario: (string | null)[][]; nombre: string }) {
  const personas = [...new Set(horario.flat().filter(Boolean))] as string[];
  const color = new Map(personas.map((p, i) => [p, COLORES[i % COLORES.length]]));
  const huecos = horario.flat().filter((c) => c === null).length;
  return (
    <Tarjeta padding style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div><h2>Ocupación semanal · {nombre}</h2><p className="cap" style={{ margin: "2px 0 0" }}>Quién cubre cada hora con la regla vigente. Los huecos quedan sin asignar.</p></div>
      <div className="fila cap" style={{ gap: 16 }}>
        {personas.map((p) => <span key={p} className="fila" style={{ gap: 6 }}><span className="celda" style={{ width: 22, height: 14, background: color.get(p) }} />{p}</span>)}
        <span className="fila" style={{ gap: 6 }}><span className="celda hueco" style={{ width: 22, height: 14 }}>–</span>Hueco (nadie)</span>
      </div>
      <div className="ocupacion" role="table" aria-label="Ocupación semanal">
        <span />
        {Array.from({ length: 24 }, (_, h) => <span key={h} className="mono cap" style={{ textAlign: "center", fontSize: 10.5 }}>{String(h).padStart(2, "0")}</span>)}
        {horario.map((fila, dia) => (
          <Fila key={dia} dia={DIAS[dia]} fila={fila} color={color} />
        ))}
      </div>
      {huecos > 0 && <Aviso tipo="atencion">Hay {entero(huecos)} horas por semana que nadie cubre: lo que entre en esas horas queda sin asignar.</Aviso>}
    </Tarjeta>
  );
}

function Fila({ dia, fila, color }: { dia: string; fila: (string | null)[]; color: Map<string, string> }) {
  return (
    <>
      <span style={{ fontWeight: 600, fontSize: 13 }}>{dia}</span>
      {fila.map((p, h) => (
        <span key={h} className={`celda${p ? "" : " hueco"}`} style={p ? { background: color.get(p) } : undefined}
          title={`${dia} ${String(h).padStart(2, "0")}:00 · ${p ?? "nadie"}`}>{p ? "" : "–"}</span>
      ))}
    </>
  );
}

function Recalcular({ cuenta }: { cuenta: DetalleCuenta }) {
  const cliente = useQueryClient();
  const avisar = useAvisos();
  const [desde, setDesde] = useState(() => diaIso(new Date(Date.now() - 30 * 86_400_000)));
  const [previa, setPrevia] = useState<ResumenReasignacion | null>(null);
  useEffect(() => setPrevia(null), [desde, cuenta.id]);
  const pedir = (soloPrevia: boolean) => api.post<ResumenReasignacion>(`/api/cuentas/${cuenta.id}/reasignar`, { desde, previa: soloPrevia });
  const verPrevia = useMutation({ mutationFn: () => pedir(true), onSuccess: setPrevia, onError: (e) => avisar((e as Error).message, "error") });
  const aplicar = useMutation({
    mutationFn: () => pedir(false),
    onSuccess: (r) => {
      avisar(`Asignación recalculada para ${cuenta.nombre}: cambiaron de asesor ${entero(r.cambiaron)} de ${entero(r.revisadas)} interacciones.`);
      setPrevia(null);
      ["cuentas", "cuenta", "interacciones", "inicio"].forEach((k) => cliente.invalidateQueries({ queryKey: [k] }));
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  return (
    <Tarjeta padding style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div><h2>Volver a calcular la asignación · {cuenta.nombre}</h2>
        <span className="cap">Vuelve a asignar las llamadas y chats desde esa fecha con las reglas guardadas (las del historial, cada una en su período). Las asignadas a mano no se tocan.</span></div>
      <div className="fila" style={{ alignItems: "end", gap: 12 }}>
        <div style={{ width: 200 }}><Texto etiqueta="Desde (00:00, hora de España)" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} /></div>
        <Boton icono="visibility" cargando={verPrevia.isPending} onClick={() => verPrevia.mutate()}>Ver vista previa</Boton>
        <Boton variante="primario" icono="sync" disabled={!previa} cargando={aplicar.isPending} onClick={() => aplicar.mutate()}
          title={previa ? undefined : "Vea la vista previa antes"}>Volver a calcular</Boton>
      </div>
      {previa && (
        <Aviso tipo={previa.cambiaron ? "atencion" : "info"}>
          {previa.revisadas === 0 ? "No hay llamadas ni chats de esta cuenta desde esa fecha."
            : <>Cambiarían de asesor <b>{entero(previa.cambiaron)} de {entero(previa.revisadas)}</b> interacciones. Quedarían así: {Object.entries(previa.por_persona).map(([p, n]) => `${p}: ${entero(n)}`).join(" · ")}.</>}
        </Aviso>
      )}
    </Tarjeta>
  );
}

function NuevaRegla({ cuenta }: { cuenta: DetalleCuenta }) {
  const cliente = useQueryClient();
  const avisar = useAvisos();
  const estrategias = useQuery({ queryKey: ["estrategias"], queryFn: () => api.get<Estrategia[]>("/api/estrategias"), staleTime: Infinity });
  const personas = useCatalogos().data?.personas ?? [];
  const inicial = cuenta.ultima_estrategia ?? "dueno_unico";
  const [estrategia, setEstrategia] = useState(inicial);
  const [parametros, setParametros] = useState<Parametros>(cuenta.ultimos_parametros ?? {});
  const [desdeSiempre, setDesdeSiempre] = useState(cuenta.ultima_estrategia === null);
  const [desde, setDesde] = useState(diaIso());
  const [corregir, setCorregir] = useState(false);
  const [previa, setPrevia] = useState<ResumenReasignacion | null>(null);
  useEffect(() => {
    setEstrategia(inicial);
    setParametros(cuenta.ultimos_parametros ?? {});
    setDesdeSiempre(cuenta.ultima_estrategia === null);
    setPrevia(null);
  }, [cuenta.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setPrevia(null), [estrategia, parametros, desdeSiempre, desde, corregir]);

  const errores = useMemo(() => faltantes(estrategia, parametros), [estrategia, parametros]);
  const cuerpo = (soloPrevia: boolean) => ({
    estrategia, parametros: completar(estrategia, parametros), desde_siempre: desdeSiempre, desde: desdeSiempre ? null : desde, previa: soloPrevia,
    corregir: !desdeSiempre && corregir,
  });
  const verPrevia = useMutation({
    mutationFn: () => api.post<ResumenReasignacion>(`/api/cuentas/${cuenta.id}/reglas`, cuerpo(true)),
    onSuccess: setPrevia,
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const guardar = useMutation({
    mutationFn: () => api.post<ResumenReasignacion>(`/api/cuentas/${cuenta.id}/reglas`, cuerpo(false)),
    onSuccess: (r) => {
      avisar(`Regla guardada para ${cuenta.nombre}. Cambiaron de asesor ${entero(r.cambiaron)} de ${entero(r.revisadas)} interacciones.`);
      setPrevia(null);
      ["cuentas", "cuenta", "interacciones", "inicio"].forEach((k) => cliente.invalidateQueries({ queryKey: [k] }));
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const Formulario = FORMULARIOS[estrategia];

  return (
    <Tarjeta padding style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="fila entre"><h2>Nueva regla · {cuenta.nombre}</h2><span className="cap">Reemplaza a la vigente desde la fecha que elija. La anterior queda en el historial.</span></div>
      {personas.length === 0 && <Aviso tipo="atencion">Primero cargue los asesores en <Link to="/asesores">Asesores</Link>.</Aviso>}
      <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="etiqueta" style={{ fontSize: 12, fontWeight: 600, color: "var(--etiqueta)", marginBottom: 6 }}>Estrategia</legend>
        <div className="grilla g3">
          {(estrategias.data ?? []).map((e) => (
            <label key={e.nombre} className="tarjeta p" style={{ display: "flex", gap: 10, cursor: "pointer", ...(estrategia === e.nombre ? { borderColor: "var(--primario)", background: "var(--fila-elegida)", boxShadow: "inset 0 0 0 1px var(--primario)" } : {}) }}>
              <input type="radio" name="estrategia" checked={estrategia === e.nombre}
                onChange={() => { setEstrategia(e.nombre); setParametros(e.nombre === cuenta.ultima_estrategia ? cuenta.ultimos_parametros ?? {} : {}); }} />
              <span><b>{e.titulo}</b><br /><span className="cap">{e.descripcion}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      {Formulario ? <Formulario personas={personas} valor={parametros} alCambiar={setParametros} /> : <Aviso tipo="error">Esta estrategia todavía no tiene formulario en el panel.</Aviso>}
      <div className="fila" style={{ alignItems: "end", gap: 16 }}>
        {cuenta.ultima_estrategia === null && <Marcador etiqueta="Vale desde siempre (también para lo anterior)" marcado={desdeSiempre} alCambiar={setDesdeSiempre} />}
        {!desdeSiempre && <div style={{ width: 200 }}><Texto etiqueta="Vigente desde (00:00, hora de España)" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} /></div>}
        {!desdeSiempre && cuenta.ultima_estrategia !== null && (
          <Marcador etiqueta="Corregir hacia atrás: reemplaza a las reglas que empiezan desde esa fecha" marcado={corregir} alCambiar={setCorregir} />
        )}
      </div>
      {corregir && !desdeSiempre && (
        <Aviso tipo="info">
          Para arreglar una regla que estaba mal: ponga la fecha desde la que tendría que haber valido. Las reglas que empezaban desde esa fecha quedan en el historial como «corregida, nunca rigió», y las llamadas y chats desde esa fecha se vuelven a asignar.
        </Aviso>
      )}
      {errores.length > 0 && <Aviso tipo="atencion">{errores.join(" ")}</Aviso>}

      {previa && (
        <div className="tarjeta p" style={{ borderColor: "var(--sin-borde)", background: "var(--aviso-fondo)", display: "flex", flexDirection: "column", gap: 6 }}>
          <b style={{ color: "var(--aviso-texto)" }}>Vista previa</b>
          {previa.revisadas === 0 ? <span>Todavía no hay llamadas ni chats de esta cuenta en ese período.</span> : (
            <>
              <span style={{ fontSize: 15 }}>Con esta regla, <b>{entero(previa.cambiaron)} de {entero(previa.revisadas)}</b> interacciones cambiarían de asesor.</span>
              <span className="cap" style={{ color: "var(--aviso-texto)" }}>
                Quedarían así: {Object.entries(previa.por_persona).map(([p, n]) => `${p}: ${entero(n)}`).join(" · ")}. Las asignadas a mano no se tocan.
              </span>
            </>
          )}
        </div>
      )}
      <div className="fila">
        <Boton icono="visibility" disabled={errores.length > 0} cargando={verPrevia.isPending} onClick={() => verPrevia.mutate()}>Ver vista previa</Boton>
        <Boton variante="primario" icono="save" disabled={errores.length > 0 || !previa} cargando={guardar.isPending} onClick={() => guardar.mutate()}
          title={previa ? undefined : "Vea la vista previa antes de guardar"}>Guardar regla</Boton>
        {!previa && errores.length === 0 && <span className="cap">Vea la vista previa antes de guardar.</span>}
      </div>
    </Tarjeta>
  );
}
