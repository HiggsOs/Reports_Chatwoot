// Avisos que confirman una acción (abajo a la derecha, se van solos).

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Aviso } from "./basicos";

type Tipo = "exito" | "error" | "info" | "atencion";
interface AvisoFlotante { id: number; tipo: Tipo; texto: string }

const Contexto = createContext<(texto: string, tipo?: Tipo) => void>(() => {});

export function ProveedorAvisos({ children }: { children: ReactNode }) {
  const [avisos, setAvisos] = useState<AvisoFlotante[]>([]);
  const avisar = useCallback((texto: string, tipo: Tipo = "exito") => {
    const id = Date.now() + Math.random();
    setAvisos((a) => [...a, { id, tipo, texto }]);
    setTimeout(() => setAvisos((a) => a.filter((x) => x.id !== id)), tipo === "error" ? 9000 : 5000);
  }, []);
  return (
    <Contexto.Provider value={avisar}>
      {children}
      <div className="aviso-flotante" aria-live="polite">
        {avisos.map((a) => <Aviso key={a.id} tipo={a.tipo}>{a.texto}</Aviso>)}
      </div>
    </Contexto.Provider>
  );
}

export const useAvisos = () => useContext(Contexto);
