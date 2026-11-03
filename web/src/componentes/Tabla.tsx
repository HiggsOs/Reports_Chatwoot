// Tabla densa con cabecera fija, selección de fila y paginación en el
// navegador (el auditor recorre cientos de filas por día).

import { useEffect, useState, type ReactNode } from "react";
import { Boton } from "./basicos";
import { entero } from "../utilidades/formato";

export interface Columna<T> {
  titulo: string;
  celda: (fila: T) => ReactNode;
  derecha?: boolean;
  ajusta?: boolean;
  ancho?: number;
}

export function Tabla<T>({
  filas, columnas, clave, elegida, alElegir, porPagina = 100, alto = 420, vacio = "No hay filas.", seleccionMultiple,
}: {
  filas: T[];
  columnas: Columna<T>[];
  clave: (fila: T) => string | number;
  elegida?: string | number | null;
  alElegir?: (fila: T) => void;
  porPagina?: number;
  alto?: number | "auto";
  vacio?: string;
  seleccionMultiple?: { elegidas: Set<string | number>; alCambiar: (v: Set<string | number>) => void };
}) {
  const [pagina, setPagina] = useState(0);
  const paginas = Math.max(1, Math.ceil(filas.length / porPagina));
  useEffect(() => setPagina(0), [filas]);
  const visibles = filas.slice(pagina * porPagina, (pagina + 1) * porPagina);
  const todas = seleccionMultiple && filas.length > 0 && filas.every((f) => seleccionMultiple.elegidas.has(clave(f)));

  if (filas.length === 0) return <p className="cap" style={{ padding: "12px 14px", margin: 0 }}>{vacio}</p>;
  return (
    <>
      <div className="tabla-caja" style={{ maxHeight: alto === "auto" ? undefined : alto }}>
        <table className="tabla">
          <thead>
            <tr>
              {seleccionMultiple && (
                <th style={{ width: 36 }}>
                  <input type="checkbox" aria-label="Elegir todas" checked={!!todas}
                    onChange={(e) => seleccionMultiple.alCambiar(e.target.checked ? new Set(filas.map(clave)) : new Set())} />
                </th>
              )}
              {columnas.map((c) => (
                <th key={c.titulo} className={c.derecha ? "derecha" : undefined} style={c.ancho ? { width: c.ancho } : undefined}>{c.titulo}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibles.map((fila) => {
              const id = clave(fila);
              const clases = [alElegir && "elegible", elegida === id && "elegida"].filter(Boolean).join(" ");
              return (
                <tr key={id} className={clases || undefined} aria-selected={alElegir ? elegida === id : undefined}
                  tabIndex={alElegir ? 0 : undefined}
                  onClick={alElegir ? () => alElegir(fila) : undefined}
                  onKeyDown={alElegir ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), alElegir(fila)) : undefined}>
                  {seleccionMultiple && (
                    <td onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" aria-label={`Elegir ${id}`} checked={seleccionMultiple.elegidas.has(id)}
                        onChange={(e) => {
                          const nuevas = new Set(seleccionMultiple.elegidas);
                          if (e.target.checked) nuevas.add(id); else nuevas.delete(id);
                          seleccionMultiple.alCambiar(nuevas);
                        }} />
                    </td>
                  )}
                  {columnas.map((c) => (
                    <td key={c.titulo} className={[c.derecha && "derecha", c.ajusta && "ajusta"].filter(Boolean).join(" ") || undefined}>{c.celda(fila)}</td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {paginas > 1 && (
        <div className="paginas">
          <span className="cap">
            {entero(pagina * porPagina + 1)}–{entero(Math.min(filas.length, (pagina + 1) * porPagina))} de {entero(filas.length)}
          </span>
          <div className="fila">
            <Boton chico icono="chevron_left" aria-label="Página anterior" disabled={pagina === 0} onClick={() => setPagina(pagina - 1)} />
            <span className="cap">Página {pagina + 1} de {paginas}</span>
            <Boton chico icono="chevron_right" aria-label="Página siguiente" disabled={pagina >= paginas - 1} onClick={() => setPagina(pagina + 1)} />
          </div>
        </div>
      )}
    </>
  );
}
