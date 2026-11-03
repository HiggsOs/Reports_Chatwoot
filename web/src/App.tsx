import { Suspense, useEffect, useState } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/cliente";
import type { EstadoConfig, Inicio } from "./api/tipos";
import { Aviso, Cargando } from "./componentes/basicos";
import { BarraLateral } from "./componentes/BarraLateral";
import { ProveedorAvisos } from "./componentes/avisos";
import { PAGINAS } from "./paginas/registro";
import Login from "./paginas/Login";

const CLAVE_CONTRAIDA = "panel:barra-contraida";

function leerContraida(): boolean {
  try {
    return localStorage.getItem(CLAVE_CONTRAIDA) === "1";
  } catch {
    return false;
  }
}

function Panel({ alSalir }: { alSalir: () => void }) {
  const [contraida, setContraida] = useState(leerContraida);
  const alternar = () => {
    setContraida(!contraida);
    try { localStorage.setItem(CLAVE_CONTRAIDA, contraida ? "0" : "1"); } catch { /* sin almacenamiento: solo esta vez */ }
  };
  const inicio = useQuery({ queryKey: ["inicio"], queryFn: () => api.get<Inicio>("/api/inicio"), refetchInterval: 60_000 });
  const estado = useQuery({ queryKey: ["estado"], queryFn: () => api.get<EstadoConfig>("/api/estado") });
  const semana = inicio.data?.semana;
  const sinAsignar = semana ? semana.llamadas_sin_asignar + semana.conversaciones_sin_asignar : 0;
  return (
    <div className="marco">
      <BarraLateral contraida={contraida} alAlternar={alternar} alSalir={alSalir}
        contadores={{
          "sin-asignar": { cantidad: sinAsignar, aviso: true },
          cuentas: { cantidad: semana?.cuentas_sin_regla ?? 0, aviso: true },
          transcripcion: { cantidad: inicio.data?.cola.error ?? 0, aviso: true },
        }} />
      <main className="contenido">
        <div className="ancho">
          {estado.data?.error_ajustes && (
            <Aviso tipo="error">
              Los ajustes guardados en el panel no son válidos y se está usando solo el entorno. Corríjalos en General o en Transcripción. {estado.data.error_ajustes}
            </Aviso>
          )}
          {!!estado.data?.ajustes_ilegibles.length && (
            <Aviso tipo="atencion">
              Estas claves se guardaron con otra llave de cifrado y no se pueden leer; cárguelas de nuevo: {estado.data.ajustes_ilegibles.join(", ")}
            </Aviso>
          )}
          <Suspense fallback={<Cargando filas={6} />}>
            <Routes>
              {PAGINAS.map(({ ruta, Componente }) => <Route key={ruta} path={`/${ruta}`} element={<Componente />} />)}
              <Route path="*" element={<Navigate to="/inicio" replace />} />
            </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}

function Raiz() {
  const cliente = useQueryClient();
  const sesion = useQuery({
    queryKey: ["sesion"],
    queryFn: () => api.get<{ usuario: string }>("/api/sesion").catch(() => null),
    staleTime: Infinity,
  });
  useEffect(() => {
    const perdida = () => cliente.setQueryData<{ usuario: string } | null>(["sesion"], null);
    window.addEventListener("panel:sin-sesion", perdida);
    return () => window.removeEventListener("panel:sin-sesion", perdida);
  }, [cliente]);

  if (sesion.isLoading) return <div className="login"><Cargando /></div>;
  if (!sesion.data) return <Login alEntrar={(u) => cliente.setQueryData<{ usuario: string } | null>(["sesion"], u)} />;
  const salir = async () => {
    await api.delete("/api/sesion").catch(() => undefined);
    cliente.clear();
    cliente.setQueryData<{ usuario: string } | null>(["sesion"], null);
  };
  return <Panel alSalir={salir} />;
}

const clienteConsultas = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: (n, e) => n < 1 && !(e as { estado?: number }).estado, refetchOnWindowFocus: false } },
});

export default function App() {
  return (
    <QueryClientProvider client={clienteConsultas}>
      <ProveedorAvisos>
        <BrowserRouter>
          <Raiz />
        </BrowserRouter>
      </ProveedorAvisos>
    </QueryClientProvider>
  );
}
