// Quién atendió y por qué (siempre visible: las cuentas son compartidas) y el
// cambio de asesor a mano.

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/cliente";
import type { Persona, TipoInteraccion } from "../api/tipos";
import { Boton, Insignia, type Tono } from "./basicos";
import { Seleccion } from "./campos";
import { useAvisos } from "./avisos";

export function origenAsignacion(asesor: string, asignacion: string): { texto: string; tono: Tono } {
  if (!asesor) return { texto: "Sin asignar", tono: "sin" };
  return asignacion === "manual" ? { texto: "Manual", tono: "manual" } : { texto: "Regla", tono: "auto" };
}

export function FranjaAsesor({ asesor, asignacion, motivo }: { asesor: string; asignacion: string; motivo: string }) {
  const origen = origenAsignacion(asesor, asignacion);
  return (
    <div className={`franja${asesor ? "" : " sin"}`}>
      <b>{asesor || "Sin asignar"}</b>
      <Insignia tono={origen.tono}>{origen.texto}</Insignia>
      <span style={{ color: "var(--etiqueta)" }}>{motivo}</span>
    </div>
  );
}

export function EditorAsignacion({ tipo, id, personaId, asignacion, personas }: {
  tipo: TipoInteraccion; id: number; personaId: number | null; asignacion: string; personas: Persona[];
}) {
  const cliente = useQueryClient();
  const avisar = useAvisos();
  const [elegida, setElegida] = useState<number>(personaId ?? 0);
  useEffect(() => setElegida(personaId ?? 0), [personaId, id]);
  const nombres = new Map(personas.map((p) => [p.id, p.nombre || p.correo]));
  const despues = (texto: string) => {
    avisar(texto);
    cliente.invalidateQueries({ queryKey: ["interacciones"] });
    cliente.invalidateQueries({ queryKey: ["inicio"] });
    cliente.invalidateQueries({ queryKey: ["historial"] });
  };
  const guardar = useMutation({
    mutationFn: () => api.put(`/api/interacciones/${tipo}/${id}/asignacion`, { persona_id: elegida || null }),
    onSuccess: () => despues(elegida ? `Asignada a ${nombres.get(elegida)} (manual).` : "Quedó sin asignar (manual)."),
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const volver = useMutation({
    mutationFn: () => api.delete(`/api/interacciones/${tipo}/${id}/asignacion`),
    onSuccess: () => despues("Volvió a la asignación automática."),
    onError: (e) => avisar((e as Error).message, "error"),
  });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <b>Asignar a mano</b>
      <Seleccion etiqueta="Asesor" valor={elegida} alCambiar={setElegida}
        opciones={[{ valor: 0, texto: "Sin asignar" }, ...personas.map((p) => ({ valor: p.id, texto: `${p.nombre || p.correo} · ${p.area}` }))]} />
      <div className="fila">
        <Boton variante="primario" icono="person_add" cargando={guardar.isPending} onClick={() => guardar.mutate()}>Guardar asignación</Boton>
        {asignacion === "manual" && (
          <Boton icono="undo" cargando={volver.isPending} onClick={() => volver.mutate()}>Volver a la regla</Boton>
        )}
      </div>
      <span className="ayuda">Una asignación hecha a mano no la cambian ni la sincronización ni las reglas.</span>
    </div>
  );
}
