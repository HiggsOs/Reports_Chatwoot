// Cliente HTTP de la API. Toda petición que cambia algo lleva la cabecera
// X-Panel (la API la exige para evitar CSRF) y los errores llegan como
// ErrorApi con el mensaje que da el servidor, listo para mostrar.

export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string) {
    super(mensaje);
  }
}

type Parametros = Record<string, string | number | boolean | (string | number)[] | undefined | null>;

export function consulta(parametros: Parametros = {}): string {
  const busqueda = new URLSearchParams();
  for (const [clave, valor] of Object.entries(parametros)) {
    if (valor === undefined || valor === null || valor === "") continue;
    if (Array.isArray(valor)) valor.forEach((v) => busqueda.append(clave, String(v)));
    else busqueda.append(clave, String(valor));
  }
  const texto = busqueda.toString();
  return texto ? `?${texto}` : "";
}

async function pedir<T>(metodo: string, ruta: string, cuerpo?: unknown): Promise<T> {
  const respuesta = await fetch(ruta, {
    method: metodo,
    credentials: "same-origin",
    headers: {
      ...(metodo === "GET" ? {} : { "X-Panel": "1" }),
      ...(cuerpo === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  });
  if (respuesta.status === 204) return undefined as T;
  const datos = await respuesta.json().catch(() => null);
  if (!respuesta.ok) {
    const detalle = datos?.detail;
    const mensaje =
      typeof detalle === "string"
        ? detalle
        : Array.isArray(detalle)
          ? "Revise los datos: hay un campo con un valor no válido."
          : `El servidor respondió ${respuesta.status}.`;
    if (respuesta.status === 401) window.dispatchEvent(new Event("panel:sin-sesion"));
    throw new ErrorApi(respuesta.status, mensaje);
  }
  return datos as T;
}

export const api = {
  get: <T>(ruta: string, parametros?: Parametros) => pedir<T>("GET", ruta + consulta(parametros)),
  post: <T>(ruta: string, cuerpo?: unknown) => pedir<T>("POST", ruta, cuerpo ?? {}),
  put: <T>(ruta: string, cuerpo?: unknown) => pedir<T>("PUT", ruta, cuerpo ?? {}),
  delete: <T>(ruta: string) => pedir<T>("DELETE", ruta),
};
