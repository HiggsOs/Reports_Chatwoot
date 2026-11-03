// Formularios de los parámetros de cada estrategia de asignación, registrados
// por nombre (como en panel/asignacion/registro.py). Una estrategia nueva
// suma su formulario aquí; la pantalla Cuentas no cambia.

import type { Persona } from "../api/tipos";
import { Boton, Icono } from "./basicos";
import { Seleccion } from "./campos";

export interface Franja { dias: number[]; inicio: string; fin: string; persona_id?: number }
export type Parametros = Record<string, unknown>;
type Formulario = (props: { personas: Persona[]; valor: Parametros; alCambiar: (p: Parametros) => void }) => JSX.Element;

const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const FRANJA_POR_DEFECTO: Franja = { dias: [0, 1, 2, 3, 4], inicio: "08:00:00", fin: "14:00:00" };
const hora = (h: string) => h.slice(0, 5);

function ElegirPersona({ etiqueta, personas, valor, alCambiar }: { etiqueta: string; personas: Persona[]; valor: unknown; alCambiar: (id: number) => void }) {
  return (
    <Seleccion etiqueta={etiqueta} valor={(valor as number) ?? 0} alCambiar={alCambiar}
      opciones={[{ valor: 0, texto: "Elija un asesor" }, ...personas.map((p) => ({ valor: p.id, texto: `${p.nombre || p.correo} · ${p.area}` }))]} />
  );
}

function EditorFranjas({ franjas, alCambiar, personas }: { franjas: Franja[]; alCambiar: (f: Franja[]) => void; personas?: Persona[] }) {
  const cambiar = (i: number, cambios: Partial<Franja>) => alCambiar(franjas.map((f, j) => (j === i ? { ...f, ...cambios } : f)));
  return (
    <div style={{ border: "1px solid var(--borde)", borderRadius: 8, overflow: "auto" }}>
      <table className="tabla">
        <thead>
          <tr>
            {personas && <th>Asesor</th>}
            {DIAS.map((d) => <th key={d} style={{ textAlign: "center" }}>{d}</th>)}
            <th>Desde</th><th>Hasta</th><th />
          </tr>
        </thead>
        <tbody>
          {franjas.map((f, i) => (
            <tr key={i}>
              {personas && (
                <td>
                  <select className="entrada chica" aria-label={`Asesor de la franja ${i + 1}`} value={f.persona_id ?? 0}
                    onChange={(e) => cambiar(i, { persona_id: Number(e.target.value) || undefined })}>
                    <option value={0}>Elija</option>
                    {personas.map((p) => <option key={p.id} value={p.id}>{p.nombre || p.correo}</option>)}
                  </select>
                </td>
              )}
              {DIAS.map((d, dia) => (
                <td key={d} style={{ textAlign: "center" }}>
                  <input type="checkbox" aria-label={`${d}, franja ${i + 1}`} checked={f.dias.includes(dia)}
                    onChange={(e) => cambiar(i, { dias: e.target.checked ? [...f.dias, dia].sort() : f.dias.filter((x) => x !== dia) })} />
                </td>
              ))}
              <td><input type="time" className="entrada chica mono" aria-label={`Desde, franja ${i + 1}`} value={hora(f.inicio)} step={300} onChange={(e) => cambiar(i, { inicio: `${e.target.value}:00` })} /></td>
              <td><input type="time" className="entrada chica mono" aria-label={`Hasta, franja ${i + 1}`} value={hora(f.fin)} step={300} onChange={(e) => cambiar(i, { fin: `${e.target.value}:00` })} /></td>
              <td><Boton chico icono="delete" aria-label={`Quitar la franja ${i + 1}`} onClick={() => alCambiar(franjas.filter((_, j) => j !== i))} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ padding: 8 }}>
        <Boton chico icono="add" onClick={() => alCambiar([...franjas, { ...FRANJA_POR_DEFECTO }])}>Agregar franja</Boton>
      </div>
    </div>
  );
}

const dueno_unico: Formulario = ({ personas, valor, alCambiar }) => (
  <div style={{ maxWidth: 360 }}>
    <ElegirPersona etiqueta="Asesor" personas={personas} valor={valor.persona_id} alCambiar={(persona_id) => alCambiar({ persona_id })} />
  </div>
);

const fijo_y_resto: Formulario = ({ personas, valor, alCambiar }) => (
  <>
    <div className="grilla g2">
      <ElegirPersona etiqueta="Persona con horario fijo" personas={personas} valor={valor.persona_fija_id} alCambiar={(id) => alCambiar({ ...valor, persona_fija_id: id })} />
      <ElegirPersona etiqueta="Fuera de ese horario (resto)" personas={personas} valor={valor.persona_resto_id} alCambiar={(id) => alCambiar({ ...valor, persona_resto_id: id })} />
    </div>
    <span className="ayuda"><Icono nombre="info" tamano={14} /> Horario fijo en hora de España; todo lo de fuera es del asesor del resto. Una franja puede cruzar la medianoche.</span>
    <EditorFranjas franjas={(valor.franjas_fijas as Franja[]) ?? [FRANJA_POR_DEFECTO]} alCambiar={(franjas_fijas) => alCambiar({ ...valor, franjas_fijas })} />
  </>
);

const franjas_completas: Formulario = ({ personas, valor, alCambiar }) => (
  <>
    <span className="ayuda">Cada franja tiene su asesor (hasta 2 por día y persona). Lo que no caiga en ninguna franja queda sin asignar.</span>
    <EditorFranjas personas={personas} franjas={(valor.franjas as Franja[]) ?? [FRANJA_POR_DEFECTO]} alCambiar={(franjas) => alCambiar({ franjas })} />
  </>
);

export const FORMULARIOS: Record<string, Formulario> = { dueno_unico, fijo_y_resto, franjas_completas };

/** Lo que falta para poder guardar, o una lista vacía. */
export function faltantes(estrategia: string, p: Parametros): string[] {
  const errores: string[] = [];
  const franjas = (lista: unknown, conPersona: boolean) => {
    const f = (lista as Franja[]) ?? [];
    if (!f.length) errores.push("Cargue al menos una franja.");
    f.forEach((x, i) => {
      if (!x.dias.length) errores.push(`Marque algún día en la franja ${i + 1}.`);
      if (conPersona && !x.persona_id) errores.push(`Elija el asesor de la franja ${i + 1}.`);
    });
  };
  if (estrategia === "dueno_unico" && !p.persona_id) errores.push("Elija el asesor.");
  if (estrategia === "fijo_y_resto") {
    if (!p.persona_fija_id) errores.push("Elija la persona con horario fijo.");
    if (!p.persona_resto_id) errores.push("Elija quién atiende el resto del tiempo.");
    franjas(p.franjas_fijas ?? [FRANJA_POR_DEFECTO], false);
  }
  if (estrategia === "franjas_completas") franjas(p.franjas ?? [FRANJA_POR_DEFECTO], true);
  return errores;
}

/** Completa lo que el formulario muestra por defecto antes de enviarlo. */
export function completar(estrategia: string, p: Parametros): Parametros {
  if (estrategia === "fijo_y_resto") return { franjas_fijas: [FRANJA_POR_DEFECTO], ...p };
  if (estrategia === "franjas_completas") return { franjas: [FRANJA_POR_DEFECTO], ...p };
  return p;
}
