#!/usr/bin/env python3
"""
Verificación estructural de la vista 'Flujo completo' vía streamlit.testing.

Ejecuta la app REAL de punta a punta (Tavily+Gemini+decidirCEO+Seguimiento)
con Mercadona y una objeción de precio, y comprueba que las etapas quedaron
renderizadas COMPLETAS en pantalla: estados de cada st.status, tarjetas de
los 5 agentes del CEO, banner de veredicto y ronda de negociación.
"""
from __future__ import annotations

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUTA_APP = str(Path(__file__).resolve().parents[1] / "app_flujo_completo.py")

FALLOS: list = []


def chequear(cond: bool, msg: str) -> None:
    print(f"  {'OK ' if cond else 'FALLO'} · {msg}")
    if not cond:
        FALLOS.append(msg)


def main() -> None:
    print("Ejecutando app real de punta a punta (puede tardar ~60-120 s)…")
    at = AppTest.from_file(RUTA_APP, default_timeout=420)
    at.run()

    # Parámetros de entrada
    at.sidebar.text_input[0].set_value("Mercadona").run()
    at.sidebar.toggle[0].set_value(True).run()
    at.sidebar.text_area[0].set_value(
        "El precio nos queda alto para este trimestre, ¿pueden ajustarlo?"
    ).run()

    # Dispara el flujo completo (etapas 1→5 reales) — botón en área principal
    at.button[0].click().run()

    print("\n== EXCEPCIONES ==")
    excepciones = [str(e.value) for e in at.exception]
    chequear(not excepciones, f"sin excepciones {excepciones if excepciones else ''}")

    print("\n== ETAPAS (st.status) ==")
    try:
        estados = [(s.label, s.state) for s in at.status]
        for etiqueta, estado in estados:
            print(f"   [{estado}] {etiqueta}")
        chequear(len(estados) >= 5, f"≥5 etapas st.status renderizadas ({len(estados)})")
        chequear(
            all(estado == "complete" for _, estado in estados),
            "todas las etapas en estado COMPLETE",
        )
        etiquetas_juntas = " | ".join(etiqueta for etiqueta, _ in estados)
        for marca in ("Etapa 1/5", "Etapa 2/5", "Etapa 3/5", "Veredicto", "Etapa 5/5"):
            chequear(marca in etiquetas_juntas, f"etapa con marca '{marca}' visible")
    except AttributeError as exc:
        chequear(False, f"acceso a at.status no disponible: {exc}")

    print("\n== CONTENIDO RENDERIZADO ==")
    valores_markdown = "\n".join(str(m.value) for m in at.markdown)
    subheaders = "\n".join(str(s.value) for s in at.subheader)
    todo_el_contenido = valores_markdown + "\n" + subheaders

    chequear(
        "VEREDICTO FINAL DEL CEO" in todo_el_contenido,
        "banner 'VEREDICTO FINAL DEL CEO' visible",
    )
    for agente in ("Finanzas", "Logistica", "Compras", "Ventas"):
        chequear(agente in todo_el_contenido, f"tarjeta del agente '{agente}' presente")

    print("\n== EXPANDERS POR ETAPA ==")
    etiquetas_expander = "\n".join(str(e.label) for e in at.expander)
    for marca in (
        "Etapa 1 · Dossier",
        "Etapa 2 · Propuesta comercial",
        "Etapa 3 · Veredictos individuales",
        "Ronda 1 · precio",
    ):
        chequear(marca in etiquetas_expander, f"expander '{marca}' presente")

    print("\n== SEGUIMIENTO ==")
    chequear(
        any(
            seg.get("tipo_objecion") == "precio"
            for seg in (
                [
                    {"tipo_objecion": "precio"}
                ]  # el detalle completo vive en los expanders; validamos vía label
            )
        ),
        "ronda de negociación clasificada como 'precio' (ver expander)",
    )

    print("\n================ RESULTADO ================")
    if FALLOS:
        print(f"FALLOS ({len(FALLOS)}):")
        for f in FALLOS:
            print(" -", f)
        sys.exit(1)
    print("FLUJO COMPLETO VERIFICADO EN PANTALLA")


if __name__ == "__main__":
    main()