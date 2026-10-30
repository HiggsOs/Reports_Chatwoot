"""Página Asesores: la lista de personas reales con su nombre y su área."""

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea
from panel.importar_asesores import ResultadoImportacion
from reporte import AREAS_VALIDAS


def mostrar(fabrica: sessionmaker[Session], importacion: ResultadoImportacion | None) -> None:
    st.title("Asesores")
    st.caption(
        "Cada asesor pertenece a un área. Los asesores que no estén en esta lista "
        "aparecen como SIN_MAPEAR en el reporte."
    )

    if importacion is not None and importacion.descartados:
        st.warning(
            "Al pasar asesores.csv a la base de datos se descartaron estas filas "
            "por no tener un área válida. Cárguelas de nuevo en esta tabla: "
            + ", ".join(importacion.descartados)
        )

    with unidad_de_trabajo(fabrica) as sesion:
        actual = {p.correo: p for p in RepositorioPersonas(sesion).listar()}
    tabla = pd.DataFrame(
        [(p.correo, p.nombre or "", p.area) for p in sorted(actual.values(), key=lambda p: p.correo)],
        columns=["email_asesor", "nombre", "area"],
    )

    editada = st.data_editor(
        tabla,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "email_asesor": st.column_config.TextColumn("Correo del asesor", required=True),
            "nombre": st.column_config.TextColumn(
                "Nombre", help="Con este nombre aparece en las reglas de las cuentas."
            ),
            "area": st.column_config.SelectboxColumn(
                "Área", options=list(AREAS_VALIDAS), required=True
            ),
        },
        key="editor_asesores",
    )

    limpias = [
        (
            str(fila.email_asesor).strip().lower(),
            str(fila.area).strip(),
            "" if pd.isna(fila.nombre) else str(fila.nombre).strip(),
        )
        for fila in editada.itertuples()
        if not pd.isna(fila.email_asesor) and str(fila.email_asesor).strip()
    ]

    borraria_todo = bool(actual) and not limpias

    if not borraria_todo:
        # Ninguna confirmación vieja debe sobrevivir al episodio de borrado
        # que la motivó: si ya no hay nada que borrar, se apaga.
        st.session_state["confirmar_borrado_asesores"] = False

    confirmado = True
    if borraria_todo:
        st.warning(
            f"La tabla quedó vacía. Si guarda, se quitarán los {len(actual)} "
            "asesores y todos aparecerán como SIN_MAPEAR en el próximo reporte."
        )
        confirmado = st.checkbox(
            "Confirmo que quiero quitar todos los asesores.",
            key="confirmar_borrado_asesores",
        )

    if st.button(
        "Guardar cambios", type="primary", disabled=borraria_todo and not confirmado
    ):
        correos = [correo for correo, _, _ in limpias]
        invalidas = [area for _, area, _ in limpias if area not in AREAS_VALIDAS]

        if len(correos) != len(set(correos)):
            st.error("Hay correos repetidos. Cada asesor debe aparecer una sola vez.")
        elif invalidas:
            st.error(f"El área debe ser {' o '.join(AREAS_VALIDAS)}.")
        else:
            asesores = [
                AsesorArea(correo=correo, area=area, nombre=nombre)
                for correo, area, nombre in limpias
            ]
            with unidad_de_trabajo(fabrica) as sesion:
                resumen = RepositorioPersonas(sesion).sincronizar_areas(asesores)
            if resumen.hubo_cambios:
                st.success(
                    f"Se guardaron {len(asesores)} asesores: {resumen.creadas} "
                    f"nuevos, {resumen.actualizadas} con otra área, "
                    f"{resumen.reactivadas} reactivados y {resumen.desactivadas} "
                    "quitados."
                )
            else:
                st.info("No había cambios que guardar.")
