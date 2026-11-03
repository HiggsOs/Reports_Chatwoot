// Asesores: personas reales con su área. No se borran: se desactivan, para no
// perder su historial.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/cliente";
import type { Persona } from "../api/tipos";
import { Aviso, Boton, Cabecera, Cargando, ErrorCarga, Insignia, Tarjeta } from "../componentes/basicos";
import { Marcador, Seleccion, Texto } from "../componentes/campos";
import { Tabla } from "../componentes/Tabla";
import { useAvisos } from "../componentes/avisos";

interface Edicion { correo: string; nombre: string; area: string; activa: boolean; nueva: boolean; original?: string }
const AREAS = [{ valor: "Comercial", texto: "Comercial" }, { valor: "RDC", texto: "RDC" }];

export default function Asesores() {
  const cliente = useQueryClient();
  const avisar = useAvisos();
  const [verInactivos, setVerInactivos] = useState(false);
  const [buscar, setBuscar] = useState("");
  const [edicion, setEdicion] = useState<Edicion | null>(null);
  const todos = useQuery({ queryKey: ["asesores"], queryFn: () => api.get<Persona[]>("/api/asesores", { inactivos: true }) });

  const guardar = useMutation({
    mutationFn: (lista: Persona[]) =>
      api.put<{ creadas: number; actualizadas: number; reactivadas: number; desactivadas: number }>("/api/asesores", {
        asesores: lista.filter((p) => p.activa).map((p) => ({ correo: p.correo, nombre: p.nombre, area: p.area })),
      }),
    onSuccess: () => {
      avisar(`Cambios guardados en ${edicion?.nombre || edicion?.correo}.`);
      setEdicion(null);
      cliente.invalidateQueries({ queryKey: ["asesores"] });
      cliente.invalidateQueries({ queryKey: ["catalogos"] });
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });

  if (todos.isLoading) return <><Cabecera titulo="Asesores" /><Cargando /></>;
  if (todos.error || !todos.data) return <><Cabecera titulo="Asesores" /><ErrorCarga error={todos.error} /></>;
  const lista = todos.data;
  const inactivos = lista.filter((p) => !p.activa).length;
  const texto = buscar.trim().toLowerCase();
  const visibles = lista.filter((p) => (verInactivos || p.activa) && (!texto || `${p.nombre ?? ""} ${p.correo}`.toLowerCase().includes(texto)));

  const enviar = () => {
    if (!edicion) return;
    const correo = edicion.correo.trim().toLowerCase();
    if (!correo.includes("@")) return avisar("Escriba un correo válido.", "error");
    const repetido = lista.find((p) => p.correo === correo && p.correo !== edicion.original);
    if (repetido) return avisar(`Ya hay un asesor con ese correo (${repetido.nombre || repetido.correo}).`, "error");
    const nueva: Persona = { id: 0, correo, nombre: edicion.nombre.trim() || null, area: edicion.area, activa: edicion.activa };
    const resto = lista.filter((p) => p.correo !== edicion.original);
    guardar.mutate([...resto, nueva]);
  };

  return (
    <>
      <Cabecera titulo="Asesores" subtitulo="Personas reales que atienden. Las cuentas compartidas se reparten entre ellas con reglas.">
        <Boton variante="primario" icono="person_add" onClick={() => setEdicion({ correo: "", nombre: "", area: "Comercial", activa: true, nueva: true })}>Nuevo asesor</Boton>
      </Cabecera>
      {lista.length === 0 && <Aviso tipo="info">Todavía no hay asesores. Cree el primero para poder asignar llamadas y chats.</Aviso>}
      <div style={{ display: "grid", gridTemplateColumns: edicion ? "minmax(0,7fr) minmax(0,4fr)" : "minmax(0,1fr)", gap: 14, alignItems: "start" }}>
        <Tarjeta>
          <div className="tarjeta-cab">
            <div style={{ width: 280 }}><Texto etiqueta="Buscar" chico type="search" placeholder="Nombre o correo" value={buscar} onChange={(e) => setBuscar(e.target.value)} /></div>
            <Marcador etiqueta={`Mostrar inactivos (${inactivos})`} marcado={verInactivos} alCambiar={setVerInactivos} />
          </div>
          <Tabla filas={visibles} clave={(p) => p.correo} elegida={edicion?.original ?? null} alto="auto"
            alElegir={(p) => setEdicion({ correo: p.correo, nombre: p.nombre ?? "", area: p.area, activa: p.activa, nueva: false, original: p.correo })}
            columnas={[
              { titulo: "Nombre", celda: (p) => <b>{p.nombre || "—"}</b> },
              { titulo: "Correo", celda: (p) => <span className="mono">{p.correo}</span> },
              { titulo: "Área", celda: (p) => <Insignia tono={p.area === "RDC" ? "manual" : "cola"}>{p.area}</Insignia> },
              { titulo: "Estado", celda: (p) => <Insignia tono={p.activa ? "ok" : "neutro"}>{p.activa ? "Activo" : "Inactivo"}</Insignia> },
            ]} />
        </Tarjeta>
        {edicion && (
          <Tarjeta padding>
            <form onSubmit={(e) => { e.preventDefault(); enviar(); }} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div className="fila entre"><h2>{edicion.nueva ? "Nuevo asesor" : `Editar · ${edicion.nombre || edicion.correo}`}</h2>
                <Boton chico icono="close" aria-label="Cerrar" onClick={() => setEdicion(null)} /></div>
              <Texto etiqueta="Nombre y apellido" value={edicion.nombre} onChange={(e) => setEdicion({ ...edicion, nombre: e.target.value })} />
              <Texto etiqueta="Correo" type="email" value={edicion.correo} onChange={(e) => setEdicion({ ...edicion, correo: e.target.value })}
                ayuda="Con este correo se reconoce su cuenta de CloudTalk o Chatwoot." />
              <Seleccion etiqueta="Área" valor={edicion.area} opciones={AREAS} alCambiar={(area) => setEdicion({ ...edicion, area })} />
              <Marcador etiqueta="Activo" marcado={edicion.activa} alCambiar={(activa) => setEdicion({ ...edicion, activa })} />
              {!edicion.activa && !edicion.nueva && (
                <Aviso tipo="atencion">Al desactivarlo, las franjas que cubre en las reglas quedan sin asesor. No se borra: se conservan sus llamadas y chats.</Aviso>
              )}
              <div className="fila">
                <Boton type="submit" variante="primario" icono="save" cargando={guardar.isPending}>Guardar cambios</Boton>
                <Boton onClick={() => setEdicion(null)}>Cancelar</Boton>
              </div>
            </form>
          </Tarjeta>
        )}
      </div>
    </>
  );
}
