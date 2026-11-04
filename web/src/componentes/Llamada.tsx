// Audio y transcripción de una llamada, sincronizados: un clic en una frase
// salta a ese momento del audio y la frase que suena queda resaltada.

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ErrorApi } from "../api/cliente";
import type { PedidoLlamada, Segmento, TranscripcionesLlamada, VersionTranscripcion } from "../api/tipos";
import { Aviso, Boton, Cargando, ErrorCarga, Icono, Insignia } from "./basicos";
import { Seleccion } from "./campos";
import { useAvisos } from "./avisos";
import { duracion, formatoFechaHora, usd } from "../utilidades/formato";

const CANALES: Record<string, string> = {
  mono: "grabación mono",
  estereo: "estéreo: un canal por persona",
  estereo_duplicado: "estéreo con el mismo audio en los dos canales",
};

function quien(s: Segmento): string {
  if (s.hablante === "agente") return "Agente";
  if (s.hablante === "cliente") return "Cliente";
  return s.etiqueta ? `Hablante ${s.etiqueta}` : "—";
}

interface Audio { url: string; mensaje: string }

function useAudio(llamadaId: number) {
  const [audio, setAudio] = useState<Audio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  useEffect(() => {
    setAudio(null);
    setError(null);
  }, [llamadaId]);
  useEffect(() => () => { if (audio) URL.revokeObjectURL(audio.url); }, [audio]);
  const cargar = async () => {
    setCargando(true);
    setError(null);
    try {
      const respuesta = await fetch(`/api/llamadas/${llamadaId}/audio`, { credentials: "same-origin" });
      if (!respuesta.ok) {
        const datos = await respuesta.json().catch(() => null);
        throw new ErrorApi(respuesta.status, datos?.detail ?? "No se pudo traer el audio.");
      }
      const mensaje = decodeURIComponent(respuesta.headers.get("X-Panel-Mensaje") ?? "");
      setAudio({ url: URL.createObjectURL(await respuesta.blob()), mensaje });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCargando(false);
    }
  };
  return { audio, error, cargando, cargar };
}

export function PanelLlamada({ llamadaId, retencionDias }: { llamadaId: number; retencionDias: number }) {
  const { audio, error, cargando, cargar } = useAudio(llamadaId);
  const reproductor = useRef<HTMLAudioElement>(null);
  const [segundo, setSegundo] = useState(0);
  const [total, setTotal] = useState(0);
  const [sonando, setSonando] = useState(false);

  // `reproducir`: al saltar desde una frase de la transcripción empieza a
  // sonar; con los botones o la barra se respeta si estaba en pausa.
  const saltar = (s: number, reproducir = true) => {
    const el = reproductor.current;
    if (!el || !Number.isFinite(s)) return;
    el.currentTime = s;
    setSegundo(s);
    if (reproducir) void el.play();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div className="tarjeta p" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div className="fila entre"><b>Audio</b>{audio && <Insignia tono="ok">Guardado {retencionDias} días</Insignia>}</div>
        {!audio ? (
          <>
            <div><Boton variante="primario" icono="play_arrow" cargando={cargando} onClick={cargar}>{cargando ? "Trayendo el audio…" : "Escuchar la llamada"}</Boton></div>
            <span className="ayuda">Descarga la grabación de CloudTalk y la guarda {retencionDias} días desde la fecha de la llamada.</span>
            {error && <Aviso tipo="error">{error}</Aviso>}
          </>
        ) : (
          <>
            <audio ref={reproductor} src={audio.url} preload="auto"
              onTimeUpdate={(e) => setSegundo(e.currentTarget.currentTime)}
              onLoadedMetadata={(e) => setTotal(e.currentTarget.duration)}
              onPlay={() => setSonando(true)} onPause={() => setSonando(false)} onEnded={() => setSonando(false)} />
            <div className="reproductor">
              <button type="button" className="boton solo-icono" aria-label="Retroceder 10 segundos" title="Retroceder 10 s"
                onClick={() => saltar(Math.max(0, segundo - 10), false)}>
                <Icono nombre="replay_10" />
              </button>
              <button type="button" className="play" aria-label={sonando ? "Pausa" : "Reproducir"}
                onClick={() => (sonando ? reproductor.current?.pause() : reproductor.current?.play())}>
                <Icono nombre={sonando ? "pause" : "play_arrow"} relleno />
              </button>
              <button type="button" className="boton solo-icono" aria-label="Avanzar 10 segundos" title="Avanzar 10 s"
                onClick={() => saltar(Math.min(total, segundo + 10), false)}>
                <Icono nombre="forward_10" />
              </button>
              <span className="mono cap" style={{ minWidth: 42, textAlign: "right" }}>{duracion(segundo)}</span>
              <div className="barra-audio" role="slider" aria-label="Posición del audio" aria-valuemin={0} aria-valuemax={Math.round(total)}
                aria-valuenow={Math.round(segundo)} aria-valuetext={`${duracion(segundo)} de ${duracion(total)}`} tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "ArrowRight") saltar(Math.min(total, segundo + 5), false);
                  if (e.key === "ArrowLeft") saltar(Math.max(0, segundo - 5), false);
                }}
                onPointerDown={(e) => {
                  // Clic o arrastre: mueve a ese punto.
                  const barra = e.currentTarget;
                  const mover = (x: number) => {
                    const caja = barra.getBoundingClientRect();
                    saltar(Math.min(1, Math.max(0, (x - caja.left) / caja.width)) * total, false);
                  };
                  barra.setPointerCapture(e.pointerId);
                  mover(e.clientX);
                  barra.onpointermove = (ev) => mover(ev.clientX);
                  barra.onpointerup = () => { barra.onpointermove = null; barra.onpointerup = null; };
                }}>
                <span className="relleno" style={{ width: `${total ? (segundo / total) * 100 : 0}%` }} />
                <span className="tirador" style={{ left: `${total ? (segundo / total) * 100 : 0}%` }} />
              </div>
              <span className="mono cap" style={{ minWidth: 42 }}>{duracion(total)}</span>
              <select className="entrada" style={{ width: 80 }} aria-label="Velocidad" defaultValue="1"
                onChange={(e) => { if (reproductor.current) reproductor.current.playbackRate = Number(e.target.value); }}>
                {["1", "1.25", "1.5", "2"].map((v) => <option key={v} value={v}>{v.replace(".", ",")}×</option>)}
              </select>
              <a className="boton solo-icono" href={audio.url} download={`llamada-${llamadaId}.mp3`} title="Descargar el audio (MP3)" aria-label="Descargar el audio (MP3)">
                <Icono nombre="download" tamano={18} />
              </a>
            </div>
            {audio.mensaje && <span className="ayuda">{audio.mensaje}</span>}
          </>
        )}
      </div>
      <Transcripcion llamadaId={llamadaId} segundo={audio ? segundo : null} alSaltar={audio ? saltar : undefined} />
    </div>
  );
}

function Transcripcion({ llamadaId, segundo, alSaltar }: { llamadaId: number; segundo: number | null; alSaltar?: (s: number) => void }) {
  const cliente = useQueryClient();
  const avisar = useAvisos();
  const consulta = useQuery({
    queryKey: ["transcripciones", llamadaId],
    queryFn: () => api.get<TranscripcionesLlamada>(`/api/llamadas/${llamadaId}/transcripciones`),
    // Mientras el pedido está en la cola, se consulta seguido para mostrar el resultado.
    refetchInterval: (q) => (enCurso(q.state.data?.pedido) ? 3000 : false),
  });
  const [versionId, setVersionId] = useState<number | null>(null);
  const [modelo, setModelo] = useState<string>("");
  const datos = consulta.data;
  useEffect(() => { setVersionId(null); setModelo(""); }, [llamadaId]);
  const version: VersionTranscripcion | undefined = datos?.versiones.find((v) => v.id === versionId) ?? datos?.versiones[0];
  const opcion = datos?.opciones.find((o) => o.clave === modelo) ?? datos?.opciones[0];

  const refrescar = () => {
    cliente.invalidateQueries({ queryKey: ["transcripciones", llamadaId] });
    cliente.invalidateQueries({ queryKey: ["interacciones"] });
  };
  const transcribir = useMutation({
    mutationFn: () => api.post<PedidoLlamada>(`/api/llamadas/${llamadaId}/transcripciones`, { proveedor: opcion?.clave }),
    onSuccess: (p) => {
      esperado.current = p.id;
      refrescar();
      cliente.invalidateQueries({ queryKey: ["transcripcion-resumen"] });
      avisar("La llamada pasó a la cola de transcripción.");
    },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  // Cuando el pedido termina, se muestra la versión nueva y se avisa.
  const pedido = datos?.pedido ?? null;
  // El pedido que se hizo desde aquí: al terminar se muestra su versión (la
  // más nueva), aunque la principal siga siendo otra.
  const esperado = useRef<number | null>(null);
  const estadoAnterior = useRef<string | null>(null);
  useEffect(() => {
    const antes = estadoAnterior.current;
    estadoAnterior.current = pedido ? `${pedido.id}:${pedido.estado}:${pedido.intentos}` : null;
    if (!pedido || antes === estadoAnterior.current) return;
    const propio = esperado.current === pedido.id;
    if (!propio && (!antes || !antes.startsWith(`${pedido.id}:`))) return;
    if (pedido.estado === "hecho") {
      esperado.current = null;
      const nueva = [...(datos?.versiones ?? [])].sort((a, b) => b.creado_en.localeCompare(a.creado_en))[0];
      setVersionId(nueva?.id ?? null);
      cliente.invalidateQueries({ queryKey: ["interacciones"] });
      avisar(nueva && !nueva.principal ? "Transcripción lista: se muestra la versión nueva. Para usarla siempre, márquela como principal." : "Transcripción lista.");
    } else if (pedido.error && !enCurso(pedido)) {
      esperado.current = null;
      avisar(`La transcripción falló: ${pedido.error}`, "error");
    }
    cliente.invalidateQueries({ queryKey: ["transcripcion-resumen"] });
  }, [pedido, datos, cliente, avisar]);
  const cambiarFrase = useMutation({
    mutationFn: ({ indice, hablante }: { indice: number; hablante: "agente" | "cliente" }) =>
      api.put(`/api/transcripciones/${version!.id}/segmentos/${indice}/hablante`, { hablante }),
    onSuccess: refrescar,
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const intercambiar = useMutation({
    mutationFn: () => api.post(`/api/transcripciones/${version!.id}/intercambiar`),
    onSuccess: () => { refrescar(); avisar("Agente y cliente intercambiados."); },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  const principal = useMutation({
    mutationFn: (id: number) => api.post(`/api/transcripciones/${id}/principal`),
    onSuccess: () => { refrescar(); avisar("Ahora es la versión principal."); },
  });

  const actual = useMemo(() => {
    if (segundo === null || !version) return -1;
    return version.segmentos.findIndex((s) => s.inicio !== null && s.fin !== null && segundo >= s.inicio && segundo < s.fin);
  }, [segundo, version]);

  if (consulta.isLoading) return <Cargando texto="Cargando la transcripción…" />;
  if (consulta.error) return <ErrorCarga error={consulta.error} />;
  if (!datos?.configurada)
    return <Aviso tipo="atencion">La transcripción no está configurada. Se configura en Transcripción › Configuración (y hace falta CloudTalk en General).</Aviso>;

  return (
    <div className="tarjeta p" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="fila entre" style={{ alignItems: "flex-end" }}>
        <b>Transcripción</b>
        {datos.versiones.length > 1 && version && (
          <div style={{ width: 360 }}>
            <Seleccion etiqueta="Versión" valor={version.id} alCambiar={setVersionId}
              opciones={[...datos.versiones].sort((a, b) => b.creado_en.localeCompare(a.creado_en)).map((v, i) => ({ valor: v.id, texto: `${v.modelo} · ${formatoFechaHora(v.creado_en)}${v.principal ? " (principal)" : ""}${i === 0 && !v.principal ? " (la más nueva)" : ""}` }))} />
          </div>
        )}
      </div>

      {(() => {
        const nueva = [...(datos.versiones ?? [])].sort((a, b) => b.creado_en.localeCompare(a.creado_en))[0];
        return nueva && version && nueva.id !== version.id ? (
          <Aviso tipo="info">
            <span className="fila" style={{ gap: 8 }}>
              Hay una versión más nueva: {nueva.modelo} · {formatoFechaHora(nueva.creado_en)}.
              <Boton chico onClick={() => setVersionId(nueva.id)}>Verla</Boton>
            </span>
          </Aviso>
        ) : null;
      })()}
      {version ? (
        <>
          <span className="cap">{version.modelo} · {CANALES[version.canales_audio] ?? version.canales_audio} · {usd(version.costo_estimado === null ? null : Number(version.costo_estimado), 4)}</span>
          <div className="dialogo" style={{ borderTop: "1px solid var(--fondo)", paddingTop: 8 }}>
            {version.segmentos.length === 0 && <span className="cap">La transcripción no tiene texto.</span>}
            {version.segmentos.map((s, i) => (
              <div key={i} className={`linea${i === actual ? " actual" : ""}`}>
                {s.inicio !== null ? (
                  <button type="button" className="saltar" disabled={!alSaltar} onClick={() => alSaltar?.(s.inicio!)}
                    aria-label={`Ir a ${duracion(s.inicio)}`} title={alSaltar ? "Ir a este momento" : "Escuche la llamada para saltar"}>
                    <Icono nombre="play_arrow" relleno tamano={14} />{duracion(s.inicio)}
                  </button>
                ) : <span />}
                <button type="button" className={`quien ${s.hablante === "agente" ? "quien-agente" : "quien-cliente"}`}
                  title={`Cambiar a ${s.hablante === "agente" ? "Cliente" : "Agente"}`} aria-label={`${quien(s)}: cambiar a ${s.hablante === "agente" ? "Cliente" : "Agente"}`}
                  disabled={cambiarFrase.isPending} onClick={() => cambiarFrase.mutate({ indice: i, hablante: s.hablante === "agente" ? "cliente" : "agente" })}>
                  {quien(s)}
                </button>
                <span>{s.texto}</span>
              </div>
            ))}
          </div>
          <QuienEsQuien version={version} alGuardar={refrescar} />
          {version.segmentos.some((s) => s.hablante === "agente" || s.hablante === "cliente") && (
            <div className="fila" style={{ gap: 8 }}>
              <Boton chico icono="swap_horiz" cargando={intercambiar.isPending} onClick={() => intercambiar.mutate()}>Intercambiar agente y cliente</Boton>
              <span className="cap">Para corregir una sola frase, haga clic en el nombre de quien habla.</span>
            </div>
          )}
          {!version.principal && (
            <div><Boton chico icono="star" cargando={principal.isPending} onClick={() => principal.mutate(version.id)}>Usar esta como principal</Boton></div>
          )}
          <span className="cap">La transcripción se conserva 3 años.</span>
        </>
      ) : (
        <span className="cap">Esta llamada todavía no tiene transcripción.</span>
      )}

      {pedido && pedido.estado !== "hecho" && <EstadoPedido pedido={pedido} />}

      {datos.opciones.length > 0 && opcion && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: "1px solid var(--fondo)", paddingTop: 10 }}>
          <Seleccion etiqueta="Proveedor y modelo" valor={opcion.clave} alCambiar={setModelo}
            opciones={datos.opciones.map((o) => ({ valor: o.clave, texto: `${o.titulo} · ${o.devuelve}` }))} />
          <div className="fila entre">
            <span className="cap">Costo estimado: <b className="mono">{usd(opcion.costo_usd, 4)}</b></span>
            <Boton variante={version ? undefined : "primario"} icono="graphic_eq" cargando={transcribir.isPending || enCurso(pedido)}
              disabled={enCurso(pedido)} onClick={() => transcribir.mutate()}>
              {enCurso(pedido) ? "En la cola…" : version ? "Transcribir de nuevo" : "Transcribir"}
            </Boton>
          </div>
          {version && <span className="ayuda">Crea una versión nueva; la principal no cambia hasta que la elija.</span>}
        </div>
      )}
    </div>
  );
}

function enCurso(pedido: PedidoLlamada | null | undefined): boolean {
  return pedido?.estado === "pendiente" || pedido?.estado === "en_proceso";
}

// El motivo ya puede terminar en punto: no se repite.
const sinPunto = (texto: string | null) => (texto ?? "").trim().replace(/\.+$/, "");

function EstadoPedido({ pedido }: { pedido: PedidoLlamada }) {
  if (pedido.estado === "en_proceso") return <Aviso tipo="info">Transcribiendo… puede tardar un minuto. Puede seguir trabajando: el pedido está en Transcripción › Cola.</Aviso>;
  if (pedido.estado === "pendiente")
    return pedido.error
      ? <Aviso tipo="atencion">Falló el intento {pedido.intentos}: {sinPunto(pedido.error)}. Se reintenta en la próxima sincronización.</Aviso>
      : <Aviso tipo="info">En la cola de transcripción. Empieza en unos segundos.</Aviso>;
  return <Aviso tipo="error">La transcripción falló tras {pedido.intentos} intentos: {sinPunto(pedido.error) || "sin motivo registrado"}. Se puede reintentar desde aquí o desde Transcripción › Cola.</Aviso>;
}

function QuienEsQuien({ version, alGuardar }: { version: VersionTranscripcion; alGuardar: () => void }) {
  const etiquetas = useMemo(
    () => [...new Set(version.segmentos.filter((s) => s.hablante === "desconocido" && s.etiqueta).map((s) => s.etiqueta!))].sort(),
    [version],
  );
  const sugerida = version.sugerencia?.etiqueta;
  const [agente, setAgente] = useState(sugerida ?? etiquetas[0] ?? "");
  useEffect(() => setAgente(sugerida ?? etiquetas[0] ?? ""), [version.id, sugerida]); // eslint-disable-line react-hooks/exhaustive-deps
  const avisar = useAvisos();
  const guardar = useMutation({
    mutationFn: () => api.post(`/api/transcripciones/${version.id}/hablantes`, { agente, etiquetas }),
    onSuccess: () => { avisar("Hablantes guardados."); alGuardar(); },
    onError: (e) => avisar((e as Error).message, "error"),
  });
  if (etiquetas.length === 0) return null;
  if (etiquetas.length === 1)
    return (
      <Aviso tipo="atencion">
        El modelo no logró separar las voces: todo quedó como «Hablante {etiquetas[0]}». Marque quién habla haciendo clic en el nombre de cada frase (cada clic alterna entre Agente y Cliente), o transcriba de nuevo con otro modelo.
      </Aviso>
    );
  return (
    <Aviso tipo="atencion">
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span>Esta versión separó las voces, pero no sabe quién es quién.</span>
        {version.sugerencia && (
          <span>Parece que el agente es el <b>Hablante {version.sugerencia.etiqueta}</b>: dijo «{version.sugerencia.frase}».</span>
        )}
        <div className="fila" role="radiogroup" aria-label="¿Quién es el agente?">
          <b>¿Quién es el agente?</b>
          {etiquetas.map((e) => (
            <label key={e} className="marcador"><input type="radio" name={`agente-${version.id}`} checked={agente === e} onChange={() => setAgente(e)} />Hablante {e}{e === sugerida ? " (sugerido)" : ""}</label>
          ))}
          <Boton chico cargando={guardar.isPending} onClick={() => guardar.mutate()}>Guardar</Boton>
        </div>
      </div>
    </Aviso>
  );
}
