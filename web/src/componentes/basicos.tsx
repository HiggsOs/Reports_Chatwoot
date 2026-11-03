// Piezas visuales básicas: icono, insignia, botón, tarjeta, aviso, métrica y
// estados de carga. Todas siguen los tokens de estilos.css.

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

export function Icono({ nombre, relleno, tamano, etiqueta }: { nombre: string; relleno?: boolean; tamano?: number; etiqueta?: string }) {
  return (
    <span
      className={`ic${relleno ? " relleno" : ""}`}
      style={tamano ? { fontSize: tamano } : undefined}
      aria-hidden={etiqueta ? undefined : true}
      role={etiqueta ? "img" : undefined}
      aria-label={etiqueta}
    >
      {nombre}
    </span>
  );
}

export type Tono = "auto" | "manual" | "sin" | "cola" | "ok" | "error" | "desviado" | "vence" | "neutro" | "nada";

export function Insignia({ tono = "neutro", children, icono }: { tono?: Tono; children: ReactNode; icono?: string }) {
  return (
    <span className={`insignia t-${tono}`}>
      {icono && <Icono nombre={icono} tamano={14} />}
      {children}
    </span>
  );
}

type Variante = "primario" | "peligro" | undefined;

interface PropsBoton extends ButtonHTMLAttributes<HTMLButtonElement> {
  icono?: string;
  variante?: Variante;
  chico?: boolean;
  cargando?: boolean;
}

export function Boton({ icono, variante, chico, cargando, children, className, disabled, type = "button", ...resto }: PropsBoton) {
  const clases = ["boton", variante, chico && "chico", !children && "solo-icono", className].filter(Boolean).join(" ");
  return (
    <button type={type} className={clases} disabled={disabled || cargando} aria-busy={cargando || undefined} {...resto}>
      {icono && <Icono nombre={cargando ? "progress_activity" : icono} tamano={chico ? 16 : 18} />}
      {children}
    </button>
  );
}

export function BotonEnlace({ a, icono, children, externo, variante, chico }: { a: string; icono?: string; children: ReactNode; externo?: boolean; variante?: Variante; chico?: boolean }) {
  const clases = ["boton", variante, chico && "chico"].filter(Boolean).join(" ");
  const contenido = (
    <>
      {icono && <Icono nombre={icono} tamano={chico ? 16 : 18} />}
      {children}
    </>
  );
  return externo ? (
    <a className={clases} href={a} target="_blank" rel="noreferrer">{contenido}</a>
  ) : (
    <Link className={clases} to={a}>{contenido}</Link>
  );
}

export function Tarjeta({ children, className = "", padding, ...resto }: { children: ReactNode; className?: string; padding?: boolean } & React.HTMLAttributes<HTMLElement>) {
  return <section className={`tarjeta${padding ? " p" : ""} ${className}`} {...resto}>{children}</section>;
}

type TipoAviso = "info" | "atencion" | "error" | "exito";
const ICONOS_AVISO: Record<TipoAviso, string> = { info: "info", atencion: "warning", error: "error", exito: "check_circle" };

export function Aviso({ tipo = "info", children }: { tipo?: TipoAviso; children: ReactNode }) {
  return (
    <div className={`aviso ${tipo}`} role={tipo === "error" ? "alert" : "status"}>
      <Icono nombre={ICONOS_AVISO[tipo]} tamano={18} />
      <div>{children}</div>
    </div>
  );
}

export function Metrica({ titulo, valor, detalle, tonoDetalle }: { titulo: string; valor: ReactNode; detalle?: ReactNode; tonoDetalle?: "bien" | "mal" }) {
  const color = tonoDetalle === "bien" ? "var(--ok-texto)" : tonoDetalle === "mal" ? "var(--error-texto)" : undefined;
  return (
    <Tarjeta className="metrica">
      <div className="titulo">{titulo}</div>
      <div className="valor">{valor}</div>
      {detalle && <div className="cap" style={{ color }}>{detalle}</div>}
    </Tarjeta>
  );
}

export function Cargando({ filas = 3, texto }: { filas?: number; texto?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }} aria-busy="true">
      {Array.from({ length: filas }, (_, i) => (
        <div key={i} className="esqueleto" style={{ width: `${96 - i * 9}%` }} />
      ))}
      {texto && <span className="cap">{texto}</span>}
    </div>
  );
}

export function ErrorCarga({ error }: { error: unknown }) {
  const mensaje = error instanceof Error ? error.message : "No se pudo cargar.";
  return <Aviso tipo="error">{mensaje}</Aviso>;
}

export function Cabecera({ titulo, subtitulo, children }: { titulo: string; subtitulo?: ReactNode; children?: ReactNode }) {
  return (
    <div className="cabecera">
      <div>
        <h1>{titulo}</h1>
        {subtitulo && <p className="cap" style={{ margin: "2px 0 0" }}>{subtitulo}</p>}
      </div>
      {children && <div className="fila">{children}</div>}
    </div>
  );
}
