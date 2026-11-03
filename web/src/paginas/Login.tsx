import { useState, type FormEvent } from "react";
import { api, ErrorApi } from "../api/cliente";
import { Aviso, Boton } from "../componentes/basicos";
import { Texto } from "../componentes/campos";

export default function Login({ alEntrar }: { alEntrar: (sesion: { usuario: string }) => void }) {
  const [usuario, setUsuario] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [entrando, setEntrando] = useState(false);

  const enviar = async (e: FormEvent) => {
    e.preventDefault();
    if (!usuario.trim() || !contrasena) {
      setError("Escribe el usuario y la contraseña.");
      return;
    }
    setEntrando(true);
    setError(null);
    try {
      alEntrar(await api.post<{ usuario: string }>("/api/sesion", { usuario, contrasena }));
    } catch (problema) {
      setError(problema instanceof ErrorApi ? problema.message : "No se pudo conectar con el panel.");
    } finally {
      setEntrando(false);
    }
  };

  return (
    <div className="login">
      <form onSubmit={enviar} noValidate>
        <div className="fila" style={{ gap: 10 }}>
          <span className="logo" style={{ width: 36, height: 36, flexBasis: 36 }}>QA</span>
          <div style={{ lineHeight: 1.2 }}>
            <b style={{ fontSize: 17 }}>Calidad · Grúas</b>
            <div className="cap">Auditoría de llamadas y chats</div>
          </div>
        </div>
        <h1 style={{ fontSize: 24 }}>Iniciar sesión</h1>
        <Texto etiqueta="Usuario" autoComplete="username" value={usuario} onChange={(e) => setUsuario(e.target.value)} autoFocus />
        <Texto etiqueta="Contraseña" type="password" autoComplete="current-password" value={contrasena} onChange={(e) => setContrasena(e.target.value)} />
        {error && <Aviso tipo="error">{error}</Aviso>}
        <Boton type="submit" variante="primario" cargando={entrando}>{entrando ? "Entrando…" : "Entrar"}</Boton>
        <p className="cap" style={{ margin: 0 }}>La contraseña se cambia en el servidor (APP_PASSWORD_HASH).</p>
      </form>
    </div>
  );
}
