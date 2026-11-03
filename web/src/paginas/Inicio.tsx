import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/cliente";
import type { Inicio as DatosInicio, PuntoSync } from "../api/tipos";
import { Aviso, Boton, Cabecera, Cargando, ErrorCarga, Icono, Insignia, Metrica, Tarjeta } from "../componentes/basicos";
import { useAvisos } from "../componentes/avisos";
import { entero, formatoFechaHora, usd, variacion } from "../utilidades/formato";

const NOMBRES: Record<string, string> = {
  cloudtalk: "CloudTalk · llamadas",
  chatwoot: "Chatwoot · conversaciones",
  audios_pendientes: "Audios por subir al servidor",
  retencion_audios: "Borrado de audios vencidos",
  transcripciones: "Transcripciones en cola",
  transcripcion_automatica: "Transcripción automática",
  retencion_transcripciones: "Borrado de transcripciones vencidas",
};

interface Pendiente { a: string; texto: string; icono: string; grave?: boolean }

function pendientes(d: DatosInicio): Pendiente[] {
  const lista: Pendiente[] = [];
  const s = d.semana;
  if (s.llamadas_sin_asignar) lista.push({ a: "/sin-asignar", texto: `${entero(s.llamadas_sin_asignar)} llamadas sin asignar`, icono: "call" });
  if (s.conversaciones_sin_asignar) lista.push({ a: "/sin-asignar", texto: `${entero(s.conversaciones_sin_asignar)} chats sin asignar`, icono: "chat" });
  if (s.cuentas_sin_regla) lista.push({ a: "/cuentas", texto: `${entero(s.cuentas_sin_regla)} cuentas sin regla`, icono: "account_tree" });
  if (d.cola.error) lista.push({ a: "/transcripcion", texto: `${entero(d.cola.error)} transcripciones con error`, icono: "error", grave: true });
  if (d.audios_por_vencer) lista.push({ a: "/llamadas", texto: `${entero(d.audios_por_vencer)} audios se borran esta semana`, icono: "timer" });
  const tope = d.config.tope_mensual_usd;
  if (tope && d.gasto_mes_usd >= (tope * d.config.aviso_porcentaje) / 100)
    lista.push({ a: "/transcripcion", texto: `Gasto de transcripción: ${usd(d.gasto_mes_usd)} de ${usd(tope)}`, icono: "payments", grave: d.gasto_mes_usd >= tope });
  return lista;
}

function TarjetaFuente({ nombre, punto, configurada }: { nombre: string; punto?: PuntoSync; configurada: boolean }) {
  const estado = !configurada ? <Insignia tono="sin">Sin configurar</Insignia>
    : !punto ? <Insignia tono="neutro">Sin sincronizar</Insignia>
    : punto.ultimo_error ? <Insignia tono="error">Falló</Insignia>
    : <Insignia tono="ok">Correcta</Insignia>;
  const resumen = (punto?.resumen ?? {}) as Record<string, number>;
  return (
    <Tarjeta padding className={punto?.ultimo_error ? "alerta" : ""}>
      <div className="fila entre"><b style={{ fontSize: 16 }}>{nombre}</b>{estado}</div>
      {punto ? (
        <>
          <p className="cap" style={{ margin: "6px 0 0" }}>
            Última corrida correcta {formatoFechaHora(punto.ultimo_exito)} · {entero(resumen.nuevas ?? 0)} nuevas, {entero(resumen.actualizadas ?? 0)} actualizadas
          </p>
          {punto.ultimo_error && (
            <div style={{ marginTop: 8 }}><Aviso tipo="error">{formatoFechaHora(punto.ultimo_intento)} · {punto.ultimo_error}</Aviso></div>
          )}
        </>
      ) : (
        <p className="cap" style={{ margin: "6px 0 0" }}>{configurada ? "Todavía no corrió." : "Configure la conexión en General."}</p>
      )}
    </Tarjeta>
  );
}

export default function Inicio() {
  const cliente = useQueryClient();
  const avisar = useAvisos();
  const consulta = useQuery({ queryKey: ["inicio"], queryFn: () => api.get<DatosInicio>("/api/inicio") });
  const sincronizar = useMutation({
    mutationFn: () => api.post<{ fuente: string; error: string | null }[]>("/api/sincronizar"),
    onSuccess: (resultados) => {
      const errores = resultados.filter((r) => r.error);
      if (errores.length) errores.forEach((r) => avisar(`${NOMBRES[r.fuente] ?? r.fuente}: ${r.error}`, "error"));
      else avisar("Sincronización terminada.");
      cliente.invalidateQueries();
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });

  if (consulta.isLoading) return <><Cabecera titulo="Inicio" /><Cargando filas={6} texto="Calculando métricas…" /></>;
  if (consulta.error || !consulta.data) return <><Cabecera titulo="Inicio" /><ErrorCarga error={consulta.error} /></>;
  const d = consulta.data;
  const faltan = [!d.config.cloudtalk && "CloudTalk", !d.config.chatwoot && "Chatwoot"].filter(Boolean) as string[];
  const tareas = pendientes(d);
  const puntos = new Map(d.sincronizacion.map((p) => [p.fuente, p]));
  const otras = d.sincronizacion.filter((p) => !["cloudtalk", "chatwoot"].includes(p.fuente));
  const v = (a: number, b: number) => variacion(a, b) ?? undefined;

  return (
    <>
      <Cabecera titulo="Inicio" subtitulo={`${formatoFechaHora(d.ahora)} (hora de España) · números de los últimos 7 días`} />

      {faltan.length > 0 && (
        <Aviso tipo="atencion">
          Falta conectar {faltan.join(" y ")}: sin eso no llegan {faltan.length === 2 ? "llamadas ni chats" : faltan[0] === "CloudTalk" ? "llamadas" : "chats"}.{" "}
          <Link to="/general">Configurar las conexiones</Link>
        </Aviso>
      )}

      <Tarjeta padding style={tareas.length ? { borderColor: "var(--sin-borde)", background: "#fffdf8" } : undefined}>
        <h2 className="sec" style={{ color: tareas.length ? "var(--sin-texto)" : undefined }}>Pendiente</h2>
        {tareas.length === 0 ? (
          <Aviso tipo="exito">Todo asignado y sin errores. Buen momento para revisar llamadas.</Aviso>
        ) : (
          <div className="grilla g3">
            {tareas.map((t) => (
              <Link key={t.texto} to={t.a} className="tarjeta p fila entre" style={{ textDecoration: "none", color: "var(--tinta)", borderColor: t.grave ? "var(--error-borde)" : "#e2d7b6" }}>
                <span className="fila"><Icono nombre={t.icono} />{t.texto}</span>
                <Icono nombre="arrow_forward" />
              </Link>
            ))}
          </div>
        )}
      </Tarjeta>

      <section>
        <h2 className="sec">La semana</h2>
        <div className="grilla g5">
          <Metrica titulo="Llamadas" valor={entero(d.semana.llamadas)} detalle={v(d.semana.llamadas, d.semana_anterior.llamadas)} />
          <Metrica titulo="Chats" valor={entero(d.semana.conversaciones)} detalle={v(d.semana.conversaciones, d.semana_anterior.conversaciones)} />
          <Metrica titulo="Llamadas sin asignar" valor={entero(d.semana.llamadas_sin_asignar)}
            detalle={v(d.semana.llamadas_sin_asignar, d.semana_anterior.llamadas_sin_asignar)}
            tonoDetalle={d.semana.llamadas_sin_asignar > d.semana_anterior.llamadas_sin_asignar ? "mal" : "bien"} />
          <Metrica titulo="Chats sin asignar" valor={entero(d.semana.conversaciones_sin_asignar)}
            detalle={v(d.semana.conversaciones_sin_asignar, d.semana_anterior.conversaciones_sin_asignar)}
            tonoDetalle={d.semana.conversaciones_sin_asignar > d.semana_anterior.conversaciones_sin_asignar ? "mal" : "bien"} />
          <Metrica titulo="Cuentas sin regla" valor={entero(d.semana.cuentas_sin_regla)} tonoDetalle="mal"
            detalle={d.semana.cuentas_sin_regla ? <Link to="/cuentas">Crear reglas</Link> : undefined} />
        </div>
      </section>

      <section>
        <div className="fila entre" style={{ marginBottom: 10 }}>
          <h2 className="sec" style={{ margin: 0 }}>Sincronización</h2>
          <Boton chico icono="sync" cargando={sincronizar.isPending} onClick={() => sincronizar.mutate()}>
            {sincronizar.isPending ? "Sincronizando…" : "Sincronizar ahora"}
          </Boton>
        </div>
        <div className="grilla g2">
          <TarjetaFuente nombre="CloudTalk · llamadas" punto={puntos.get("cloudtalk")} configurada={d.config.cloudtalk} />
          <TarjetaFuente nombre="Chatwoot · conversaciones" punto={puntos.get("chatwoot")} configurada={d.config.chatwoot} />
        </div>
        <p className="cap">La sincronización trae lo nuevo cada {d.config.intervalo_minutos} minutos. La primera vez puede tardar varios minutos.</p>
        {otras.length > 0 && (
          <details>
            <summary className="cap" style={{ cursor: "pointer" }}>Tareas de mantenimiento</summary>
            <ul className="cap">
              {otras.map((p) => (
                <li key={p.fuente}>
                  <b>{NOMBRES[p.fuente] ?? p.fuente}</b> · última {formatoFechaHora(p.ultimo_exito)} · {p.ultimo_error ? `con error: ${p.ultimo_error}` : "correcta"}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </>
  );
}
