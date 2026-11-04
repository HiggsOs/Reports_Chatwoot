// Registro de páginas: sección, título, ruta, icono y componente. La barra
// lateral y las rutas salen de aquí; agregar una pantalla es sumar una línea.

import { lazy, type ComponentType } from "react";

export interface EntradaPagina { seccion: string; titulo: string; ruta: string; icono: string; Componente: ComponentType }

const perezosa = (cargar: () => Promise<{ default: ComponentType }>) => lazy(cargar);

export const SECCIONES = ["Operación", "Reportes", "Configuración"] as const;

export const PAGINAS: EntradaPagina[] = [
  { seccion: "Operación", titulo: "Inicio", ruta: "inicio", icono: "home", Componente: perezosa(() => import("./Inicio")) },
  { seccion: "Operación", titulo: "Sin asignar", ruta: "sin-asignar", icono: "assignment_late", Componente: perezosa(() => import("./SinAsignar")) },
  { seccion: "Operación", titulo: "Llamadas", ruta: "llamadas", icono: "call", Componente: perezosa(() => import("./Llamadas")) },
  { seccion: "Operación", titulo: "Conversaciones", ruta: "conversaciones", icono: "chat", Componente: perezosa(() => import("./Conversaciones")) },
  { seccion: "Operación", titulo: "Historial del cliente", ruta: "historial", icono: "history", Componente: perezosa(() => import("./Historial")) },
  { seccion: "Reportes", titulo: "Reporte de Chatwoot", ruta: "reporte-chatwoot", icono: "forum", Componente: perezosa(() => import("./ReporteChatwoot")) },
  { seccion: "Configuración", titulo: "General", ruta: "general", icono: "settings", Componente: perezosa(() => import("./General")) },
  { seccion: "Configuración", titulo: "Asesores", ruta: "asesores", icono: "group", Componente: perezosa(() => import("./Asesores")) },
  { seccion: "Configuración", titulo: "Cuentas", ruta: "cuentas", icono: "account_tree", Componente: perezosa(() => import("./Cuentas")) },
  { seccion: "Configuración", titulo: "Transcripción", ruta: "transcripcion", icono: "graphic_eq", Componente: perezosa(() => import("./Transcripcion")) },
];
