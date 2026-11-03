import { describe, expect, it } from "vitest";
import { completar, faltantes } from "../componentes/formulariosRegla";

describe("formularios de reglas de asignación", () => {
  it("dueño único pide el asesor", () => {
    expect(faltantes("dueno_unico", {})).toEqual(["Elija el asesor."]);
    expect(faltantes("dueno_unico", { persona_id: 3 })).toEqual([]);
  });

  it("fijo y resto pide las dos personas y una franja con días", () => {
    expect(faltantes("fijo_y_resto", {})).toHaveLength(2);
    const sinDias = { persona_fija_id: 1, persona_resto_id: 2, franjas_fijas: [{ dias: [], inicio: "08:00:00", fin: "14:00:00" }] };
    expect(faltantes("fijo_y_resto", sinDias)).toEqual(["Marque algún día en la franja 1."]);
  });

  it("franjas completas pide el asesor de cada franja", () => {
    expect(faltantes("franjas_completas", { franjas: [{ dias: [0], inicio: "08:00:00", fin: "14:00:00" }] }))
      .toEqual(["Elija el asesor de la franja 1."]);
  });

  it("completa la franja por defecto que muestra el formulario", () => {
    expect(completar("fijo_y_resto", { persona_fija_id: 1 })).toHaveProperty("franjas_fijas");
    expect(completar("dueno_unico", { persona_id: 1 })).toEqual({ persona_id: 1 });
  });
});
