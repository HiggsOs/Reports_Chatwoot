// Formato en español de España: dd/mm/aaaa, 24 h en Europe/Madrid, coma
// decimal, +34 612 345 678.

const ZONA = "Europe/Madrid";
const fecha = new Intl.DateTimeFormat("es-ES", { timeZone: ZONA, day: "2-digit", month: "2-digit", year: "numeric" });
const fechaHora = new Intl.DateTimeFormat("es-ES", {
  timeZone: ZONA, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const hora = new Intl.DateTimeFormat("es-ES", { timeZone: ZONA, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

export const formatoFecha = (iso: string | null | undefined) => (iso ? fecha.format(new Date(iso)) : "—");
export const formatoFechaHora = (iso: string | null | undefined) =>
  iso ? fechaHora.format(new Date(iso)).replace(",", "") : "—";
export const formatoHora = (iso: string | null | undefined) => (iso ? hora.format(new Date(iso)) : "");

export function numero(valor: number | null | undefined, decimales = 2): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return "—";
  return new Intl.NumberFormat("es-ES", { minimumFractionDigits: decimales, maximumFractionDigits: decimales, useGrouping: "always" } as unknown as Intl.NumberFormatOptions).format(valor);
}
export const entero = (valor: number | null | undefined) => numero(valor, 0);
export const usd = (valor: number | null | undefined, decimales = 2) =>
  valor === null || valor === undefined ? "sin precio" : `${numero(valor, decimales)} USD`;

export function duracion(segundos: number | null | undefined): string {
  if (segundos === null || segundos === undefined) return "";
  const s = Math.max(0, Math.floor(segundos));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** +34612345678 → +34 612 345 678. Lo que no es un móvil o fijo español queda igual. */
export function telefono(valor: string | null | undefined): string {
  if (!valor) return "";
  const m = valor.match(/^\+34(\d{3})(\d{3})(\d{3})$/);
  return m ? `+34 ${m[1]} ${m[2]} ${m[3]}` : valor;
}

/** Fecha local (aaaa-mm-dd) para los filtros, en hora de España. */
export function diaIso(fechaBase: Date = new Date(), sumarDias = 0): string {
  const d = new Date(fechaBase.getTime() + sumarDias * 86400000);
  const partes = new Intl.DateTimeFormat("en-CA", { timeZone: ZONA, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  return partes;
}

export const capitalizar = (texto: string) => (texto ? texto[0].toUpperCase() + texto.slice(1) : texto);

export function variacion(actual: number, anterior: number): string | null {
  if (!anterior) return null;
  const cambio = Math.round(((actual - anterior) / anterior) * 100);
  return `${cambio > 0 ? "+" : ""}${cambio} % vs. la semana anterior`;
}
