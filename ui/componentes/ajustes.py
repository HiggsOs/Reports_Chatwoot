"""Editar ajustes del panel: leer el valor vigente, mostrar de dónde sale,
pedir claves sin mostrarlas y guardar solo si la configuración resultante es
válida."""

from collections.abc import Mapping

import streamlit as st

from config import ConfigError, cargar_config
from panel.ajustes import Cifrador, LecturaAjustes, RepositorioAjustes, enmascarar, origenes
from panel.db.base import unidad_de_trabajo
from ui.componentes import avisos

ORIGEN = {"panel": "cargado en el panel", "entorno": "del entorno del servidor"}


class FormularioAjustes:
    """Valores actuales, de dónde salen y cómo se guardan (patrón Form Object).

    Lo usan General y la configuración de Transcripción: los dos editan ajustes
    del panel y los validan igual antes de guardarlos.
    """

    def __init__(self, fabrica, entorno: Mapping[str, str], lectura: LecturaAjustes, recargar):
        self.fabrica = fabrica
        self.entorno = dict(entorno)
        self.efectivo = {**self.entorno, **lectura.valores}
        self.origen = origenes(self.entorno, lectura)
        self.recargar = recargar

    def valor(self, clave: str, defecto: str = "") -> str:
        return (self.efectivo.get(clave) or defecto).strip()

    def ayuda(self, clave: str) -> str | None:
        origen = self.origen.get(clave)
        return f"Valor {ORIGEN[origen]}." if origen else None

    def texto(self, etiqueta: str, clave: str, defecto: str = "", **extra) -> str:
        return st.text_input(etiqueta, value=self.valor(clave, defecto), help=self.ayuda(clave), **extra)

    def secreto(self, etiqueta: str, clave: str, key: str) -> str:
        """Vacío: se deja la clave guardada."""
        actual = self.valor(clave)
        origen = self.origen.get(clave)
        marcador = (
            f"Guardada ({ORIGEN[origen]}): {enmascarar(actual)}. Escriba otra para cambiarla."
            if actual
            else "Pegue la clave"
        )
        return st.text_input(etiqueta, type="password", placeholder=marcador, key=key, autocomplete="off")

    def con_cambios(self, cambios: dict[str, str | None]) -> dict[str, str]:
        """Cómo quedaría la configuración si se guardan estos cambios."""
        nuevo = dict(self.efectivo)
        for clave, valor in cambios.items():
            if valor is None or valor == "":
                # Sin valor en el panel vuelve a valer el del entorno.
                nuevo.pop(clave, None)
                if self.entorno.get(clave):
                    nuevo[clave] = self.entorno[clave]
            else:
                nuevo[clave] = valor
        return nuevo

    def guardar(self, cambios: dict[str, str | None], aviso: str) -> None:
        try:
            cargar_config(self.con_cambios(cambios))
        except ConfigError as error:
            st.error(f"No se guardó: {error}")
            return
        with unidad_de_trabajo(self.fabrica) as sesion:
            RepositorioAjustes(sesion, Cifrador.desde_entorno(self.entorno)).guardar(cambios)
        self.recargar()
        avisos.dejar(aviso)
        st.rerun()
