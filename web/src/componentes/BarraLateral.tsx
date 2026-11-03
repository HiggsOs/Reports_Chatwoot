// Barra lateral en grupos. Se contrae a una tira de iconos de 64 px; la
// preferencia se recuerda en este navegador.

import { NavLink } from "react-router-dom";
import { Icono } from "./basicos";
import { PAGINAS, SECCIONES } from "../paginas/registro";

export interface Contadores { [ruta: string]: { cantidad: number; aviso?: boolean } | undefined }

export function BarraLateral({ contraida, alAlternar, contadores, alSalir }: {
  contraida: boolean; alAlternar: () => void; contadores: Contadores; alSalir: () => void;
}) {
  const textoBoton = contraida ? "Expandir la barra lateral" : "Contraer la barra lateral";
  return (
    <nav className={`lateral${contraida ? " contraida" : ""}`} aria-label="Navegación principal">
      <div className="marca">
        <span className="logo">QA</span>
        {!contraida && (
          <div className="marca-texto"><b>Calidad · Grúas</b><span className="cap">Auditoría de asesores</span></div>
        )}
        <button type="button" className="boton-icono" onClick={alAlternar} aria-label={textoBoton} title={textoBoton} aria-expanded={!contraida}>
          <Icono nombre={contraida ? "left_panel_open" : "left_panel_close"} tamano={20} />
        </button>
      </div>

      {SECCIONES.map((seccion) => (
        <div className="grupo" key={seccion}>
          {contraida ? <div className="grupo-linea" /> : <div className="grupo-titulo">{seccion}</div>}
          {PAGINAS.filter((p) => p.seccion === seccion).map((p) => {
            const contador = contadores[p.ruta];
            const etiqueta = p.titulo + (contador?.cantidad ? ` (${contador.cantidad})` : "");
            return (
              <NavLink key={p.ruta} to={`/${p.ruta}`} end className={({ isActive }) => `enlace-nav${isActive ? " activo" : ""}`}
                title={contraida ? etiqueta : undefined} aria-label={contraida ? etiqueta : undefined}>
                <span className="nombre"><Icono nombre={p.icono} tamano={20} />{!contraida && p.titulo}</span>
                {contador?.cantidad ? (
                  contraida
                    ? <span className={`punto${contador.aviso ? " ambar" : ""}`} aria-hidden>{contador.cantidad > 99 ? "99+" : contador.cantidad}</span>
                    : <span className={`contador${contador.aviso ? " ambar" : ""}`}>{contador.cantidad > 99 ? "99+" : contador.cantidad}</span>
                ) : null}
              </NavLink>
            );
          })}
        </div>
      ))}

      <div className="pie-lateral">
        {!contraida && <span className="cap">Horas en hora de España (Europe/Madrid).</span>}
        <button type="button" className="boton" onClick={alSalir} title="Cerrar sesión" aria-label="Cerrar sesión">
          <Icono nombre="logout" />{!contraida && "Cerrar sesión"}
        </button>
      </div>
    </nav>
  );
}
