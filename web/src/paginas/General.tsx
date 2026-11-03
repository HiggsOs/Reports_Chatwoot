// General: conexiones con CloudTalk, Chatwoot, el almacén de audios y la
// sincronización. Lo que se guarda aquí pisa a las variables de entorno.

import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/cliente";
import type { Inicio, Prueba, ValorAjuste } from "../api/tipos";
import { Aviso, Boton, Cabecera, Cargando, ErrorCarga, Icono, Insignia, Tarjeta } from "../componentes/basicos";
import { Campo, Seleccion, Texto } from "../componentes/campos";
import { useAvisos } from "../componentes/avisos";
import { formatoFechaHora } from "../utilidades/formato";

type Ajustes = Record<string, ValorAjuste>;
const ORIGEN: Record<string, string> = { panel: "Cargado en el panel.", entorno: "Del entorno del servidor." };

/** Estado de un formulario de ajustes: valores editados y qué cambió. */
function useFormulario(ajustes: Ajustes, claves: string[]) {
  const iniciales = () => Object.fromEntries(claves.map((k) => [k, ajustes[k]?.secreto ? "" : ajustes[k]?.valor ?? ""]));
  const [valores, setValores] = useState<Record<string, string>>(iniciales);
  useEffect(() => setValores(iniciales()), [ajustes]); // eslint-disable-line react-hooks/exhaustive-deps
  const cambios = Object.fromEntries(
    claves.filter((k) => (ajustes[k]?.secreto ? valores[k] !== "" : valores[k] !== (ajustes[k]?.valor ?? ""))).map((k) => [k, valores[k]]),
  );
  return { valores, poner: (k: string, v: string) => setValores((x) => ({ ...x, [k]: v })), cambios, hayCambios: Object.keys(cambios).length > 0 };
}

function CampoAjuste({ etiqueta, clave, ajustes, form, tipo = "text", ayuda, placeholder }: {
  etiqueta: string; clave: string; ajustes: Ajustes; form: ReturnType<typeof useFormulario>; tipo?: string; ayuda?: ReactNode; placeholder?: string;
}) {
  const a = ajustes[clave];
  const secreto = a?.secreto;
  return (
    <Texto etiqueta={etiqueta} type={secreto ? "password" : tipo} autoComplete="off" value={form.valores[clave] ?? ""}
      onChange={(e) => form.poner(clave, e.target.value)}
      placeholder={secreto ? (a?.valor ? `Guardada: ${a.valor}. Escriba otra para cambiarla.` : "Pegue la clave") : placeholder}
      ayuda={ayuda ?? (a?.origen ? ORIGEN[a.origen] : undefined)} />
  );
}

function Seccion({ icono, titulo, descripcion, estado, children, pie }: { icono: string; titulo: string; descripcion: ReactNode; estado?: ReactNode; children: ReactNode; pie: ReactNode }) {
  return (
    <Tarjeta>
      <div className="lado" style={{ padding: 20 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <span className="fila" style={{ gap: 10 }}>
            <span className="logo" style={{ background: "var(--cola-fondo)", color: "var(--primario)", width: 36, height: 36, flexBasis: 36 }}><Icono nombre={icono} tamano={22} /></span>
            <h2 style={{ fontSize: 20 }}>{titulo}</h2>
          </span>
          {estado}
          <div className="cap" style={{ display: "flex", flexDirection: "column", gap: 6 }}>{descripcion}</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>{children}</div>
      </div>
      <div className="tarjeta-pie">{pie}</div>
    </Tarjeta>
  );
}

function usePrueba(destino: string) {
  return useMutation({ mutationFn: (valores: Record<string, string>) => api.post<Prueba>(`/api/ajustes/probar/${destino}`, { valores }) });
}

function ResultadoPrueba({ prueba }: { prueba: ReturnType<typeof usePrueba> }) {
  if (prueba.data) return <Aviso tipo={prueba.data.ok ? "exito" : "error"}>{prueba.data.mensaje}</Aviso>;
  if (prueba.error) return <Aviso tipo="error">{(prueba.error as Error).message}</Aviso>;
  return null;
}

export default function General() {
  const cliente = useQueryClient();
  const avisar = useAvisos();
  const ajustes = useQuery({ queryKey: ["ajustes-generales"], queryFn: () => api.get<Ajustes>("/api/ajustes/general") });
  const inicio = useQuery({ queryKey: ["inicio"], queryFn: () => api.get<Inicio>("/api/inicio") });
  const guardar = useMutation({
    mutationFn: ({ valores }: { valores: Record<string, string>; aviso: string }) => api.put("/api/ajustes/general", { valores }),
    onSuccess: (_r, { aviso }) => { avisar(aviso); cliente.invalidateQueries(); },
    onError: (e) => avisar((e as Error).message, "error"),
  });

  if (ajustes.isLoading) return <><Cabecera titulo="Configuración general" /><Cargando filas={6} /></>;
  if (ajustes.error || !ajustes.data) return <><Cabecera titulo="Configuración general" /><ErrorCarga error={ajustes.error} /></>;
  const a = ajustes.data;
  const puntos = new Map((inicio.data?.sincronizacion ?? []).map((p) => [p.fuente, p]));
  const estado = (fuente: string, configurada: boolean) => {
    const p = puntos.get(fuente);
    if (!configurada) return <Insignia tono="sin">Sin configurar</Insignia>;
    if (p?.ultimo_error) return <Insignia tono="error">Error en la última corrida</Insignia>;
    if (p?.ultimo_exito) return <Insignia tono="ok">Correcta · {formatoFechaHora(p.ultimo_exito)}</Insignia>;
    return <Insignia tono="neutro">Sin sincronizar todavía</Insignia>;
  };
  const errorDe = (fuente: string) => {
    const p = puntos.get(fuente);
    return p?.ultimo_error ? <Aviso tipo="error">{formatoFechaHora(p.ultimo_intento)} · {p.ultimo_error}</Aviso> : null;
  };
  const config = inicio.data?.config;

  return (
    <>
      <Cabecera titulo="Configuración general"
        subtitulo="Conexiones con CloudTalk, Chatwoot y el servidor de los audios. Lo que se guarda aquí reemplaza a las variables de entorno; la sincronización lo toma en su próximo ciclo. Las claves se guardan cifradas y nunca se vuelven a mostrar completas." />

      <CloudTalk a={a} estado={estado("cloudtalk", !!config?.cloudtalk)} error={errorDe("cloudtalk")} guardar={guardar} />
      <Chatwoot a={a} estado={estado("chatwoot", !!config?.chatwoot)} error={errorDe("chatwoot")} guardar={guardar} />
      <Almacen a={a} guardar={guardar} />
      <Sincronizacion a={a} guardar={guardar} />
      <p className="cap">El usuario y la contraseña del panel, DATABASE_URL y la llave de cifrado (PANEL_CLAVE_CIFRADO o APP_COOKIE_KEY) solo se cambian en el servidor.</p>
    </>
  );
}

type Guardar = ReturnType<typeof useMutation<unknown, Error, { valores: Record<string, string>; aviso: string }>>;

function Botones({ form, guardar, aviso, prueba, extra }: { form: ReturnType<typeof useFormulario>; guardar: Guardar; aviso: string; prueba?: ReturnType<typeof usePrueba>; extra?: ReactNode }) {
  return (
    <div className="fila">
      {extra}
      {prueba && <Boton icono="network_check" cargando={prueba.isPending} onClick={() => prueba.mutate(form.valores)}>Probar con estos datos</Boton>}
      <Boton variante="primario" icono="save" disabled={!form.hayCambios} cargando={guardar.isPending}
        onClick={() => guardar.mutate({ valores: form.cambios, aviso })}>Guardar</Boton>
    </div>
  );
}

function CloudTalk({ a, estado, error, guardar }: { a: Ajustes; estado: ReactNode; error: ReactNode; guardar: Guardar }) {
  const form = useFormulario(a, ["CLOUDTALK_API_KEY_ID", "CLOUDTALK_API_KEY_SECRET"]);
  const prueba = usePrueba("cloudtalk");
  return (
    <Seccion icono="call" titulo="CloudTalk" estado={estado}
      descripcion={<><span>Trae las llamadas, sus grabaciones y las cuentas de los agentes.</span><span>La clave se crea en CloudTalk: Cuenta › Configuración › API.</span></>}
      pie={<><span className="cap">{form.hayCambios ? "Hay cambios sin guardar." : " "}</span><Botones form={form} guardar={guardar} prueba={prueba} aviso="Conexión con CloudTalk guardada." /></>}>
      <div className="grilla g2">
        <CampoAjuste etiqueta="ID de la clave de API" clave="CLOUDTALK_API_KEY_ID" ajustes={a} form={form} />
        <CampoAjuste etiqueta="Clave secreta" clave="CLOUDTALK_API_KEY_SECRET" ajustes={a} form={form} />
      </div>
      <ResultadoPrueba prueba={prueba} />
      {error}
    </Seccion>
  );
}

function Chatwoot({ a, estado, error, guardar }: { a: Ajustes; estado: ReactNode; error: ReactNode; guardar: Guardar }) {
  const form = useFormulario(a, ["CHATWOOT_BASE_URL", "CHATWOOT_ACCOUNT_ID", "CHATWOOT_API_TOKEN", "CHATWOOT_DIAS_RELECTURA", "CHATWOOT_DIAS_FINALIZACION"]);
  const prueba = usePrueba("chatwoot");
  return (
    <Seccion icono="chat" titulo="Chatwoot" estado={estado}
      descripcion={<><span>Trae las conversaciones, sus mensajes y notas internas.</span><span>El token sale de Chatwoot: Perfil › Ajustes del perfil › Token de acceso. Use el de un administrador: con el de un agente solo se ven sus bandejas.</span></>}
      pie={<><span className="cap">{form.hayCambios ? "Hay cambios sin guardar." : " "}</span><Botones form={form} guardar={guardar} prueba={prueba} aviso="Conexión con Chatwoot guardada." /></>}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)", gap: 12 }}>
        <CampoAjuste etiqueta="URL de la instancia" clave="CHATWOOT_BASE_URL" ajustes={a} form={form} tipo="url" placeholder="https://chat.miempresa.com" />
        <CampoAjuste etiqueta="ID de la cuenta" clave="CHATWOOT_ACCOUNT_ID" ajustes={a} form={form} placeholder="1"
          ayuda={<>Es el número de la URL: /app/accounts/<b>1</b>/…</>} />
      </div>
      <CampoAjuste etiqueta="Token de acceso" clave="CHATWOOT_API_TOKEN" ajustes={a} form={form} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
        <CampoAjuste etiqueta="Releer las conversaciones de los últimos (días)" clave="CHATWOOT_DIAS_RELECTURA" ajustes={a} form={form} tipo="number" placeholder="14"
          ayuda="Las conversaciones cambian después de creadas: se resuelven o se reasignan." />
        <CampoAjuste etiqueta="Unir abandonadas a la anterior hasta (días)" clave="CHATWOOT_DIAS_FINALIZACION" ajustes={a} form={form} tipo="number" placeholder="7"
          ayuda="Una conversación sin asesor con un solo mensaje del cliente cuenta como el final de su conversación anterior." />
      </div>
      <ResultadoPrueba prueba={prueba} />
      {error}
    </Seccion>
  );
}

const ALMACENES = [
  { valor: "", texto: "No guardar los audios" },
  { valor: "sftp", texto: "SFTP del hosting" },
  { valor: "local", texto: "Carpeta local (solo desarrollo)" },
];

function Almacen({ a, guardar }: { a: Ajustes; guardar: Guardar }) {
  const form = useFormulario(a, ["ALMACEN_TIPO", "FTP_HOST", "FTP_PORT", "FTP_USER", "FTP_PASSWORD", "FTP_DIR", "SFTP_HUELLA_HOST", "AUDIO_RETENCION_DIAS"]);
  const prueba = usePrueba("almacen");
  const huella = useMutation({
    mutationFn: () => api.post<{ huella: string }>("/api/ajustes/huella", { host: form.valores.FTP_HOST, puerto: Number(form.valores.FTP_PORT || 22) }),
    onSuccess: (r) => form.poner("SFTP_HUELLA_HOST", r.huella),
  });
  const tipo = form.valores.ALMACEN_TIPO ?? "";
  const estado = tipo ? <Insignia tono="ok">{ALMACENES.find((x) => x.valor === (a.ALMACEN_TIPO?.valor ?? ""))?.texto}</Insignia>
    : <Insignia tono="sin">Sin almacén: los audios no se guardan</Insignia>;
  return (
    <Seccion icono="dns" titulo="Audios (SFTP)" estado={estado}
      descripcion={<><span>Dónde se guarda la copia de cada audio escuchado. El panel lo borra al cumplir el plazo.</span>
        <span>Se verifica la huella del servidor en cada conexión: sin eso, otro servidor podría hacerse pasar por el suyo y recibir las grabaciones.</span></>}
      pie={<><span className="cap">La prueba sube un archivo de prueba, lo lee y lo borra.</span><Botones form={form} guardar={guardar} prueba={prueba} aviso="Almacén de audios guardado." /></>}>
      <Seleccion etiqueta="Guardar los audios en" valor={tipo} opciones={ALMACENES} alCambiar={(v) => form.poner("ALMACEN_TIPO", v)} />
      {tipo === "sftp" && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0,3fr) minmax(0,1fr)", gap: 12 }}>
            <CampoAjuste etiqueta="Servidor" clave="FTP_HOST" ajustes={a} form={form} placeholder="almacen.miempresa.es" />
            <CampoAjuste etiqueta="Puerto" clave="FTP_PORT" ajustes={a} form={form} tipo="number" placeholder="22" />
          </div>
          <div className="grilla g2">
            <CampoAjuste etiqueta="Usuario" clave="FTP_USER" ajustes={a} form={form} />
            <CampoAjuste etiqueta="Contraseña" clave="FTP_PASSWORD" ajustes={a} form={form} />
          </div>
          <CampoAjuste etiqueta="Carpeta remota" clave="FTP_DIR" ajustes={a} form={form} placeholder="/" />
          <Campo etiqueta="Huella del servidor (SHA256)" ayuda="Compárela con la que muestre su hosting antes de guardar.">
            {(id) => (
              <div className="fila" style={{ flexWrap: "nowrap" }}>
                <input id={id} className="entrada mono" value={form.valores.SFTP_HUELLA_HOST ?? ""} onChange={(e) => form.poner("SFTP_HUELLA_HOST", e.target.value)} placeholder="SHA256:…" />
                <Boton icono="fingerprint" cargando={huella.isPending} disabled={!form.valores.FTP_HOST} onClick={() => huella.mutate()}>Traer la huella</Boton>
              </div>
            )}
          </Campo>
          {huella.error && <Aviso tipo="error">{(huella.error as Error).message}</Aviso>}
          {huella.data && <Aviso tipo="atencion">Huella leída: {huella.data.huella}. Compruebe que coincide con la de su hosting antes de guardar.</Aviso>}
        </>
      )}
      <div style={{ maxWidth: 320 }}>
        <CampoAjuste etiqueta="Conservar los audios (días)" clave="AUDIO_RETENCION_DIAS" ajustes={a} form={form} tipo="number" placeholder="90"
          ayuda="Desde la fecha de la llamada. Las transcripciones se conservan 3 años." />
      </div>
      <ResultadoPrueba prueba={prueba} />
    </Seccion>
  );
}

function Sincronizacion({ a, guardar }: { a: Ajustes; guardar: Guardar }) {
  const form = useFormulario(a, ["SYNC_INTERVALO_MINUTOS", "SYNC_DIAS_INICIALES"]);
  return (
    <Seccion icono="sync" titulo="Sincronización"
      descripcion={<span>Cada cuánto se traen las llamadas y conversaciones nuevas, y cuánto historial se trae la primera vez.</span>}
      pie={<><span className="cap">Vale desde el próximo ciclo.</span><Botones form={form} guardar={guardar} aviso="Sincronización guardada. Vale desde el próximo ciclo." /></>}>
      <div className="grilla g2">
        <CampoAjuste etiqueta="Sincronizar cada (minutos)" clave="SYNC_INTERVALO_MINUTOS" ajustes={a} form={form} tipo="number" placeholder="15" />
        <CampoAjuste etiqueta="La primera vez, traer los últimos (días)" clave="SYNC_DIAS_INICIALES" ajustes={a} form={form} tipo="number" placeholder="30" />
      </div>
    </Seccion>
  );
}
