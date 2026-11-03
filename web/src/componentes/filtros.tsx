// Filtros de Llamadas y Conversaciones, en una fila.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/cliente";
import type { Catalogos } from "../api/tipos";
import { Marcador, SelectorMultiple, Texto } from "./campos";
import { diaIso } from "../utilidades/formato";

export interface Filtros {
  desde: string; hasta: string; personas: number[]; cuentas: number[]; cliente: string; sin_asignar: boolean;
}

export function useFiltros(dias = 7): [Filtros, (f: Partial<Filtros>) => void] {
  const [filtros, setFiltros] = useState<Filtros>({
    desde: diaIso(new Date(), -dias), hasta: diaIso(), personas: [], cuentas: [], cliente: "", sin_asignar: false,
  });
  return [filtros, (cambios) => setFiltros((f) => ({ ...f, ...cambios }))];
}

export function useCatalogos() {
  return useQuery({ queryKey: ["catalogos"], queryFn: () => api.get<Catalogos>("/api/catalogos"), staleTime: 300_000 });
}

export function BarraFiltros({ filtros, cambiar, plataforma }: { filtros: Filtros; cambiar: (f: Partial<Filtros>) => void; plataforma: string }) {
  const catalogos = useCatalogos().data;
  return (
    <div className="tarjeta p" style={{ display: "grid", gridTemplateColumns: "140px 140px minmax(0,1.5fr) minmax(0,1.3fr) minmax(0,1.3fr) auto", gap: 12, alignItems: "end" }}>
      <Texto etiqueta="Desde" type="date" value={filtros.desde} max={filtros.hasta} onChange={(e) => cambiar({ desde: e.target.value })} />
      <Texto etiqueta="Hasta" type="date" value={filtros.hasta} min={filtros.desde} onChange={(e) => cambiar({ hasta: e.target.value })} />
      <SelectorMultiple etiqueta="Asesores" elegidos={filtros.personas} alCambiar={(personas) => cambiar({ personas })}
        opciones={(catalogos?.personas ?? []).map((p) => ({ valor: p.id, texto: p.nombre || p.correo }))} />
      <SelectorMultiple etiqueta="Cuentas" vacio="Todas" elegidos={filtros.cuentas} alCambiar={(cuentas) => cambiar({ cuentas })}
        opciones={(catalogos?.cuentas[plataforma] ?? []).map((c) => ({ valor: c.id, texto: c.nombre }))} />
      <Texto etiqueta="Cliente" type="search" placeholder="Nombre o teléfono" value={filtros.cliente} onChange={(e) => cambiar({ cliente: e.target.value })} />
      <div style={{ height: 36, display: "flex", alignItems: "center" }}>
        <Marcador etiqueta="Solo sin asignar" marcado={filtros.sin_asignar} alCambiar={(sin_asignar) => cambiar({ sin_asignar })} />
      </div>
    </div>
  );
}
