// Campos de formulario con su etiqueta (siempre un <label> real).

import { useEffect, useId, useRef, useState, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { Icono } from "./basicos";

export function Campo({ etiqueta, ayuda, children, id }: { etiqueta: string; ayuda?: ReactNode; children: (id: string) => ReactNode; id?: string }) {
  const generado = useId();
  const propio = id ?? generado;
  return (
    <div className="campo">
      <label htmlFor={propio}>{etiqueta}</label>
      {children(propio)}
      {ayuda && <span className="ayuda">{ayuda}</span>}
    </div>
  );
}

export function Texto({ etiqueta, ayuda, chico, ...resto }: { etiqueta: string; ayuda?: ReactNode; chico?: boolean } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <Campo etiqueta={etiqueta} ayuda={ayuda}>
      {(id) => <input id={id} className={`entrada${chico ? " chica" : ""}`} {...resto} />}
    </Campo>
  );
}

export function Seleccion<T extends string | number>({
  etiqueta, ayuda, valor, opciones, alCambiar, ...resto
}: { etiqueta: string; ayuda?: ReactNode; valor: T; opciones: { valor: T; texto: string }[]; alCambiar: (v: T) => void } & Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange">) {
  return (
    <Campo etiqueta={etiqueta} ayuda={ayuda}>
      {(id) => (
        <select
          id={id}
          className="entrada"
          value={String(valor)}
          onChange={(e) => {
            const elegida = opciones.find((o) => String(o.valor) === e.target.value);
            if (elegida) alCambiar(elegida.valor);
          }}
          {...resto}
        >
          {opciones.map((o) => (
            <option key={String(o.valor)} value={String(o.valor)}>{o.texto}</option>
          ))}
        </select>
      )}
    </Campo>
  );
}

export function Marcador({ etiqueta, marcado, alCambiar }: { etiqueta: ReactNode; marcado: boolean; alCambiar: (v: boolean) => void }) {
  return (
    <label className="marcador">
      <input type="checkbox" checked={marcado} onChange={(e) => alCambiar(e.target.checked)} />
      {etiqueta}
    </label>
  );
}

/** Varias opciones con fichas (como st.multiselect). Vacío = «todas». */
export function SelectorMultiple<T extends string | number>({
  etiqueta, opciones, elegidos, alCambiar, vacio = "Todos",
}: { etiqueta: string; opciones: { valor: T; texto: string }[]; elegidos: T[]; alCambiar: (v: T[]) => void; vacio?: string }) {
  const [abierto, setAbierto] = useState(false);
  const caja = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!abierto) return;
    const cerrar = (e: MouseEvent) => {
      if (caja.current && !caja.current.contains(e.target as Node)) setAbierto(false);
    };
    document.addEventListener("mousedown", cerrar);
    return () => document.removeEventListener("mousedown", cerrar);
  }, [abierto]);
  const textos = new Map(opciones.map((o) => [o.valor, o.texto]));
  const alternar = (v: T) => alCambiar(elegidos.includes(v) ? elegidos.filter((e) => e !== v) : [...elegidos, v]);
  return (
    <div className="campo" ref={caja}>
      <span className="etiqueta" id={id}>{etiqueta}</span>
      <div className="multi">
        <button type="button" className="multi-boton" aria-labelledby={id} aria-expanded={abierto} onClick={() => setAbierto(!abierto)}
          onKeyDown={(e) => e.key === "Escape" && setAbierto(false)}>
          {elegidos.length === 0 && <span className="cap" style={{ paddingLeft: 4 }}>{opciones.length ? vacio : "No hay opciones"}</span>}
          {elegidos.map((v) => (
            <span className="ficha" key={String(v)}>{textos.get(v) ?? v}</span>
          ))}
          <span className="flecha"><Icono nombre="expand_more" /></span>
        </button>
        {abierto && opciones.length > 0 && (
          <div className="multi-lista" role="group" aria-labelledby={id}>
            {opciones.map((o) => (
              <label key={String(o.valor)}>
                <input type="checkbox" checked={elegidos.includes(o.valor)} onChange={() => alternar(o.valor)} />
                {o.texto}
              </label>
            ))}
            {elegidos.length > 0 && (
              <button type="button" className="boton-texto" style={{ padding: "6px 8px" }} onClick={() => alCambiar([])}>Quitar todos</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
