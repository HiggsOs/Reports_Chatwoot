import { describe, expect, it } from "vitest";
import { duracion, entero, formatoFecha, formatoFechaHora, numero, telefono, usd, variacion } from "../utilidades/formato";

describe("formato en español de España", () => {
  it("fechas en dd/mm/aaaa y 24 h en Europe/Madrid", () => {
    expect(formatoFecha("2026-10-30T22:30:00Z")).toBe("30/10/2026");
    expect(formatoFechaHora("2026-10-30T22:30:00Z")).toBe("30/10/2026 23:30");
    expect(formatoFechaHora("2026-07-01T22:30:00Z")).toBe("02/07/2026 00:30");
    expect(formatoFechaHora(null)).toBe("—");
  });

  it("números con coma decimal y punto de miles", () => {
    expect(numero(1234.5)).toBe("1.234,50");
    expect(entero(1908)).toBe("1.908");
    expect(usd(0.0066, 4)).toBe("0,0066 USD");
    expect(usd(null)).toBe("sin precio");
  });

  it("duración y teléfono", () => {
    expect(duracion(272)).toBe("4:32");
    expect(duracion(null)).toBe("");
    expect(telefono("+34612345678")).toBe("+34 612 345 678");
    expect(telefono("6123456")).toBe("6123456");
  });

  it("variación respecto de la semana anterior", () => {
    expect(variacion(12, 10)).toBe("+20 % vs. la semana anterior");
    expect(variacion(5, 0)).toBeNull();
  });
});
