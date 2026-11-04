// Reporte de Chatwoot: las conversaciones del rango consultadas en el momento,
// para descargarlas en CSV (como en la versión anterior del panel). Corre en el
// servidor; aquí se inicia, se sigue su avance y se descarga.

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/cliente";
import type { EstadoConfig } from "../api/tipos";
import { Aviso, Boton, BotonDescarga, Cabecera, Tarjeta } from "../componentes/basicos";
import { Texto } from "../componentes/campos";
import { Tabla } from "../componentes/Tabla";
import { diaIso, entero } from "../utilidades/formato";

type Fila = Record<string, string>;
interface EstadoReporte {
  id: string; desde: string; hasta: string; estado: "en_curso" | "listo" | "error";
  hechas: number; total: number; error: string | null; sin_mapear: string[]; filas: Fila[] | null;
}

const DIAS_RANGO_AMPLIO = 90;
const COLUMNAS: { clave: string; titulo: string }[] = [
  { clave: "conversacion_id", titulo: "ID" },
  { clave: "asesor", titulo: "Asesor" },
  { clave: "email_asesor", titulo: "Correo" },
  { clave: "area", titulo: "Área" },
  { clave: "fecha_creacion", titulo: "Creada" },
  { clave: "canal", titulo: "Canal" },
  { clave: "etiquetas", titulo: "Etiquetas" },
  { clave: "direccion", titulo: "Dirección" },
  { clave: "estado", titulo: "Estado" },
  { clave: "fecha_cierre", titulo: "Cierre" },
  { clave: "tiempo_resolucion_horas", titulo: "Horas" },
  { clave: "cierre_aproximado", titulo: "Cierre aprox." },
];

const primeroDeMes = () => `${diaIso(new Date()).slice(0, 8)}01`;

export default function ReporteChatwoot() {
  const [desde, setDesde] = useState(primeroDeMes);
  const [hasta, setHasta] = useState(() => diaIso(new Date()));
  const [id, setId] = useState<string | null>(null);
  const estadoConfig = useQuery({ queryKey: ["estado"], queryFn: () => api.get<EstadoConfig>("/api/estado") });

  const iniciar = useMutation({
    mutationFn: () => api.post<{ id: string }>("/api/reportes/chatwoot", { desde, hasta }),
    onSuccess: (r) => setId(r.id),
  });
  const reporte = useQuery({
    queryKey: ["reporte-chatwoot", id],
    queryFn: () => api.get<EstadoReporte>(`/api/reportes/chatwoot/${id}`),
    enabled: !!id,
    staleTime: Infinity,
    refetchInterval: (q) => (q.state.data?.estado === "en_curso" || !q.state.data ? 1000 : false),
  });

  const invertido = desde > hasta;
  const dias = (new Date(hasta).getTime() - new Date(desde).getTime()) / 86_400_000;
  const datos = reporte.data;
  const enCurso = iniciar.isPending || (!!id && (!datos || datos.estado === "en_curso") && !reporte.error);

  return (
    <>
      <Cabecera titulo="Reporte de Chatwoot"
        subtitulo="Conversaciones de Chatwoot consultadas en el momento, para descargar en CSV. La página Conversaciones muestra lo mismo desde la base, con el asesor real." />
      {estadoConfig.data && !estadoConfig.data.chatwoot && (
        <Aviso tipo="atencion">Chatwoot no está conectado. Cargue la URL, la cuenta y el token en General.</Aviso>
      )}
      <Tarjeta padding>
        <form className="fila" style={{ alignItems: "flex-end", flexWrap: "wrap" }}
          onSubmit={(e) => { e.preventDefault(); if (!invertido) iniciar.mutate(); }}>
          <div style={{ width: 170 }}><Texto etiqueta="Desde" type="date" value={desde} max={hasta} onChange={(e) => setDesde(e.target.value)} /></div>
          <div style={{ width: 170 }}><Texto etiqueta="Hasta" type="date" value={hasta} min={desde} onChange={(e) => setHasta(e.target.value)} /></div>
          <Boton type="submit" variante="primario" icono="play_arrow" cargando={enCurso} disabled={invertido || !desde || !hasta}>Generar reporte</Boton>
        </form>
        {invertido && <Aviso tipo="atencion">La fecha inicial no puede ser posterior a la final.</Aviso>}
        {!invertido && dias > DIAS_RANGO_AMPLIO && (
          <Aviso tipo="info">El rango supera {DIAS_RANGO_AMPLIO} días. La consulta puede tardar varios minutos la primera vez.</Aviso>
        )}
      </Tarjeta>

      {iniciar.error && <Aviso tipo="error">{(iniciar.error as Error).message}</Aviso>}
      {reporte.error && <Aviso tipo="error">{(reporte.error as Error).message}</Aviso>}

      {datos?.estado === "en_curso" && (
        <Tarjeta padding>
          <p className="cap" style={{ margin: "0 0 8px" }}>
            {datos.total ? `Procesando ${entero(datos.hechas)} de ${entero(datos.total)}…` : "Consultando conversaciones…"}
          </p>
          <progress max={datos.total || 1} value={datos.hechas} style={{ width: "100%" }} />
        </Tarjeta>
      )}
      {datos?.estado === "error" && <Aviso tipo="error">{datos.error}</Aviso>}

      {datos?.estado === "listo" && datos.filas && (
        datos.filas.length === 0 ? (
          <Aviso tipo="atencion">No hay conversaciones en el rango seleccionado.</Aviso>
        ) : (
          <>
            {datos.sin_mapear.length > 0 && (
              <Aviso tipo="atencion">Estos asesores no tienen área asignada. Agréguelos en la página Asesores: {datos.sin_mapear.join(", ")}</Aviso>
            )}
            <Tarjeta>
              <div className="tarjeta-cab">
                <span><b>{entero(datos.filas.length)}</b> conversaciones del {datos.desde} al {datos.hasta}.</span>
                <BotonDescarga ruta={(formato) => `/api/reportes/chatwoot/${datos.id}/${formato}`} variante="primario" />
              </div>
              <Tabla filas={datos.filas} clave={(f) => f.conversacion_id} alto={520}
                columnas={COLUMNAS.map(({ clave, titulo }) => ({ titulo, celda: (f: Fila) => f[clave] || "—" }))} />
            </Tarjeta>
          </>
        )
      )}
    </>
  );
}
