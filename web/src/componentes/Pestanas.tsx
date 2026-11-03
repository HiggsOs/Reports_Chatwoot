import { Icono } from "./basicos";

export interface Pestana<T extends string> { id: T; titulo: string; icono?: string; contador?: number }

export function Pestanas<T extends string>({ pestanas, activa, alCambiar }: { pestanas: Pestana<T>[]; activa: T; alCambiar: (id: T) => void }) {
  return (
    <div className="pestanas" role="tablist">
      {pestanas.map((p) => (
        <button key={p.id} type="button" role="tab" aria-selected={p.id === activa}
          className={`pestana${p.id === activa ? " activa" : ""}`} onClick={() => alCambiar(p.id)}>
          {p.icono && <Icono nombre={p.icono} />}
          {p.titulo}
          {p.contador ? <span className="insignia t-error" style={{ height: 18 }}>{p.contador}</span> : null}
        </button>
      ))}
    </div>
  );
}
