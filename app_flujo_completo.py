#!/usr/bin/env python3
"""
EUREKA · Vista "FLUJO COMPLETO" de la línea de ventas hacia clientes.

Pipeline visual con evolución en tiempo real (st.status progresivos):

    1️⃣ MARKETING      → investigación del prospecto (Tavily + Gemini)
    2️⃣ PROPUESTA      → catálogo + tier determinístico + redacción
    3️⃣ CEO ×5         → finanzas/logística/compras/ventas/observador
                         (tarjetas paralelas con su veredicto individual)
    4️⃣ VEREDICTO      → decisión final del CEO (banner coloreado)
    5️⃣ SEGUIMIENTO    → opcional: objeción del cliente por rondas

Cada etapa queda expandible (expander) con su detalle completo tras
terminar, y los resultados persisten entre interacciones vía session_state.

Uso:
    streamlit run app_flujo_completo.py
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def _cargar_modulo(archivo: str, nombre: str):
    """Carga un módulo con guion en el nombre desde src/agents."""
    spec = importlib.util.spec_from_file_location(
        nombre, RAIZ / "src" / "agents" / archivo
    )
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


mp = _cargar_modulo("marketing-prospeccion.py", "flujo_marketing_prospeccion")
pc = _cargar_modulo("propuestas-comerciales.py", "flujo_propuestas_comerciales")
sc = _cargar_modulo("seguimiento-comercial.py", "flujo_seguimiento_comercial")

st.set_page_config(
    page_title="EUREKA · Flujo completo",
    page_icon="🧭",
    layout="wide",
)

COLOR_DECISION = {
    "aprobado": "#2e7d32",
    "rechazado": "#c62828",
    "reformular": "#ef6c00",
    "escalado_a_humano": "#ed6c02",
}
ETIQUETA_DECISION = {
    "aprobado": "✔ APROBADO",
    "rechazado": "✗ RECHAZADO",
    "reformular": "↻ REFORMULAR",
    "escalado_a_humano": "⤴ ESCALADO A HUMANO",
}
AGENTES_BASE = ("finanzas", "logistica", "compras", "ventas")


def _icono_valida(valida: Any) -> str:
    return "✅" if valida else ("❌" if valida is False else "•")


# ── Estado de sesión ─────────────────────────────────────────────────────────
for clave, defecto in {
    "fc_dossier": None,
    "fc_propuesta": None,
    "fc_seguimientos": [],       # lista de rondas ejecutadas
    "fc_errores": [],
    "fc_ejecutado_en": None,
}.items():
    st.session_state.setdefault(clave, defecto)

# ── Barra lateral ────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🧭 Flujo completo")
    st.caption("Línea de venta de agentes IA a medida")
    empresa = st.text_input("Empresa prospecto", value="Mercadona")
    rubro = st.text_input("Rubro (opcional, orienta la búsqueda)", "")
    margen = st.slider(
        "Margen bruto estimado del deal (%)", 10, 60, 30,
        help="Viaja a decidirCEO(): Finanzas veta bajo el objetivo (25%).",
    )
    st.divider()
    st.subheader("5️⃣ Seguimiento (opcional)")
    activar_seg = st.toggle("Simular objeción del cliente")
    respuesta_cliente = st.text_area(
        "Respuesta / objeción (texto libre)",
        "",
        height=110,
        disabled=not activar_seg,
        placeholder="Ej: El precio nos queda alto, ¿pueden ajustarlo?",
    )
    ronda = st.number_input(
        "Ronda de negociación", min_value=1, max_value=9,
        value=len(st.session_state.fc_seguimientos) + 1,
        disabled=not activar_seg,
    )

ejecutar = st.button(
    "🚀 Ejecutar flujo completo",
    type="primary",
    use_container_width=True,
    disabled=not empresa.strip(),
)

# ── Pipeline en tiempo real ──────────────────────────────────────────────────
if ejecutar:
    st.session_state.fc_errores = []
    barra = st.progress(0.0, text="Preparando pipeline…")
    errores: List[str] = []

    # ═══ ETAPA 1 · MARKETING ══════════════════════════════════════════════
    with st.status(
        f"🔎 Etapa 1/5 · Investigando a **{empresa}**…", expanded=True
    ) as estado_1:
        st.write("Fase 1 · Búsqueda web con Tavily (snippets + URLs reales)")
        st.write("Fase 2 · Redacción del dossier con Gemini (texto)")
        try:
            dossier = mp.investigar_empresa(empresa.strip(), rubro.strip() or None)
            if "error" in dossier:
                raise RuntimeError(str(dossier["error"]))
            st.write(
                f"✅ Dossier listo · confianza: **{dossier.get('confianza')}** · "
                f"fuentes: {len(dossier.get('fuentes', []))}"
            )
            estado_1.update(
                label=f"🔎 Etapa 1/5 · Dossier de {empresa} completo",
                state="complete",
                expanded=False,
            )
        except Exception as exc:  # noqa: BLE001
            estado_1.update(
                label="🔎 Etapa 1/5 · FALLÓ", state="error", expanded=True
            )
            st.error(f"Marketing/prospección falló: {exc}")
            errores.append(f"marketing: {exc}")
    barra.progress(
        0.2,
        text="Etapa 1/5 completada" if not errores else "Detenido en etapa 1",
    )

    if not errores:
        st.session_state.fc_dossier = dossier

        # ═══ ETAPA 2 · PROPUESTA COMERCIAL ════════════════════════════════
        with st.status(
            "📝 Etapa 2/5 · Cruzando dossier con el catálogo y redactando…",
            expanded=False,
        ) as estado_2:
            st.write("Selección determinística de tier (código, no LLM)")
            st.write("Validación previa vía decidirCEO() — 5 agentes TS")
            st.write("Redacción comercial con Gemini")
            try:
                propuesta = pc.crear_propuesta(
                    dossier, margen_bruto_estimado=float(margen)
                )
                if "error" in propuesta:
                    raise RuntimeError(str(propuesta["error"]))
                st.write(
                    f"✅ Propuesta lista · tier {propuesta.get('tier_recomendado')} "
                    f"· CEO: **{(propuesta.get('validacion_ceo') or {}).get('decision')}**"
                )
                estado_2.update(
                    label=(
                        f"📝 Etapa 2/5 · Propuesta tier "
                        f"{propuesta.get('tier_recomendado')} · CEO: "
                        f"{(propuesta.get('validacion_ceo') or {}).get('decision')}"
                    ),
                    state="complete",
                    expanded=False,
                )
            except Exception as exc:  # noqa: BLE001
                estado_2.update(
                    label="📝 Etapa 2/5 · FALLÓ", state="error", expanded=True
                )
                st.error(f"Propuestas comerciales falló: {exc}")
                errores.append(f"propuestas: {exc}")
        barra.progress(0.45, text="Etapa 2/5 completada")

        if not errores:
            st.session_state.fc_propuesta = propuesta

    # ═══ ETAPA 3 · LOS 5 AGENTES DEL CEO (tarjetas paralelas) ═════════════
    if st.session_state.fc_propuesta:
        validacion = st.session_state.fc_propuesta.get("validacion_ceo") or {}
        aportes = validacion.get("aportes_agentes") or {}
        with st.status(
            "🏛️ Etapa 3/5 · Los 5 agentes del CEO evalúan en paralelo…",
            expanded=True,
        ) as estado_3:
            columnas = st.columns(len(AGENTES_BASE))
            for col, nombre in zip(columnas, AGENTES_BASE):
                aporte = aportes.get(nombre) or {}
                valida = aporte.get("valida")
                col.metric(
                    nombre.capitalize(),
                    _icono_valida(valida)
                    + (" OK" if valida else (" ✗" if valida is False else " ?")),
                )
                mensaje = str(aporte.get("mensaje", ""))[:120]
                if mensaje:
                    col.caption(mensaje)
            observador = aportes.get("ventas-observador") or {}
            if observador:
                st.write(
                    f"👁 ventas-observador · severidad: "
                    f"**{observador.get('severidad', '—')}** · recomendación: "
                    f"`{observador.get('recomendacionAlCeo', '—')}`"
                )
            estado_3.update(
                label="🏛️ Etapa 3/5 · Veredictos individuales listos",
                state="complete",
                expanded=False,
            )
        barra.progress(0.7, text="Etapa 3/5 completada")

        # ═══ ETAPA 4 · VEREDICTO FINAL ════════════════════════════════════
        decision = str(validacion.get("decision", "")).lower()
        color = COLOR_DECISION.get(decision, "#455a64")
        etiqueta = ETIQUETA_DECISION.get(decision, decision.upper() or "—")
        with st.status(
            "🏁 Etapa 4/5 · Consolidando veredicto del CEO…", expanded=True
        ) as estado_4:
            st.write(validacion.get("detalle") or "")
            st.markdown(
                f"""
                <div style="padding:1rem 1.25rem;border-radius:.6rem;
                            background:{color};margin:.25rem 0 .75rem;">
                  <span style="font-size:.8rem;color:rgba(255,255,255,.85);
                               letter-spacing:.14em;">VEREDICTO FINAL DEL CEO</span>
                  <h2 style="color:#fff;margin:.15rem 0 0;">{etiqueta}</h2>
                </div>
                """,
                unsafe_allow_html=True,
            )
            estado_4.update(
                label=f"🏁 Etapa 4/5 · Veredicto: {etiqueta}",
                state="complete",
                expanded=False,
            )
        barra.progress(0.85, text="Etapa 4/5 · Veredicto emitido")

    # ═══ ETAPA 5 · SEGUIMIENTO OPCIONAL ═══════════════════════════════════
    if (
        not errores
        and st.session_state.fc_propuesta
        and activar_seg
        and respuesta_cliente.strip()
    ):
        with st.status(
            f"🤝 Etapa 5/5 · Procesando objeción (ronda {int(ronda)})…",
            expanded=True,
        ) as estado_5:
            estado_previo = None
            if st.session_state.fc_seguimientos:
                ultimo = st.session_state.fc_seguimientos[-1]
                estado_previo = ultimo.get("estado_negociacion")
            try:
                seguimiento = sc.negociar_ronda(
                    st.session_state.fc_propuesta,
                    respuesta_cliente.strip(),
                    ronda=int(ronda),
                    estado_previo=estado_previo,
                )
                st.write(
                    f"Objeción clasificada: **{seguimiento.get('tipo_objecion')}** · "
                    f"requiere humano: "
                    f"**{seguimiento.get('requiere_intervencion_humana')}**"
                )
                estado_5.update(
                    label=(
                        f"🤝 Etapa 5/5 · Ronda {int(ronda)} procesada "
                        f"({seguimiento.get('tipo_objecion')})"
                    ),
                    state="complete",
                    expanded=False,
                )
                st.session_state.fc_seguimientos.append(seguimiento)
            except Exception as exc:  # noqa: BLE001
                estado_5.update(
                    label="🤝 Etapa 5/5 · FALLÓ", state="error", expanded=True
                )
                st.error(f"Seguimiento falló: {exc}")
                errores.append(f"seguimiento: {exc}")
        barra.progress(1.0, text="Flujo completo finalizado ✅")
    elif ejecutar and not errores and st.session_state.fc_propuesta:
        barra.progress(1.0, text="Flujo completo finalizado (sin seguimiento) ✅")

    if errores:
        st.session_state.fc_errores = errores
    st.session_state.fc_ejecutado_en = datetime.now()

# ── Render persistente de resultados (expander por etapa) ────────────────────
def _tarjetas_agentes(aportes: Dict[str, Any], expandido: bool = False) -> None:
    columnas = st.columns(len(AGENTES_BASE))
    for col, nombre in zip(columnas, AGENTES_BASE):
        aporte = aportes.get(nombre) or {}
        valida = aporte.get("valida")
        col.markdown(f"**{nombre.capitalize()}** {_icono_valida(valida)}")
        mensaje = str(aporte.get("mensaje", ""))
        if mensaje:
            col.caption(mensaje[:140])
    observador = aportes.get("ventas-observador")
    if observador:
        st.info(
            f"👁 **ventas-observador** · severidad: "
            f"**{observador.get('severidad', '—')}** · recomendación al CEO: "
            f"`{observador.get('recomendacionAlCeo', '—')}`\n\n"
            + "\n".join(f"- {r}" for r in observador.get("riesgos", []) or [])
        )


def _banner_veredicto(decision: str) -> None:
    decision_l = str(decision).lower()
    color = COLOR_DECISION.get(decision_l, "#455a64")
    etiqueta = ETIQUETA_DECISION.get(decision_l, decision_l.upper() or "—")
    st.markdown(
        f"""
        <div style="padding:1rem 1.25rem;border-radius:.6rem;background:{color};
                    margin:.25rem 0 .75rem;">
          <span style="font-size:.8rem;color:rgba(255,255,255,.85);
                       letter-spacing:.14em;">VEREDICTO FINAL DEL CEO</span>
          <h2 style="color:#fff;margin:.15rem 0 0;">{etiqueta}</h2>
        </div>
        """,
        unsafe_allow_html=True,
    )


if st.session_state.fc_errores:
    with st.expander("❌ Errores de la última ejecución", expanded=True):
        for e in st.session_state.fc_errores:
            st.error(e)

dossier = st.session_state.fc_dossier
propuesta = st.session_state.fc_propuesta

if not st.session_state.fc_ejecutado_en:
    st.info(
        "⚙️ Configura la empresa prospecto en la barra lateral y pulsa "
        "**🚀 Ejecutar flujo completo** para ver las 5 etapas en vivo."
    )

if st.session_state.fc_ejecutado_en:
    st.caption(
        f"🕒 Última ejecución: "
        f"{st.session_state.fc_ejecutado_en:%d/%m/%Y %H:%M:%S}"
    )

if dossier:
    validacion = (propuesta or {}).get("validacion_ceo") or {}
    _banner_veredicto(str(validacion.get("decision", "")))

    with st.expander("🔎 Etapa 1 · Dossier del prospecto", expanded=not propuesta):
        c1, c2, c3 = st.columns(3)
        c1.metric("Rubro", str(dossier.get("rubro", "—"))[:28])
        c2.metric("Tamaño", str(dossier.get("tamano_estimado", "—")))
        c3.metric("Confianza", str(dossier.get("confianza", "—")))
        senales = dossier.get("senales_de_necesidad") or []
        if senales:
            st.markdown("**Señales detectadas:**")
            for s in senales:
                st.markdown(f"- {s}")
        with st.expander("Dossier JSON completo"):
            st.json(dossier)

if propuesta:
    validacion = propuesta.get("validacion_ceo") or {}
    aportes = validacion.get("aportes_agentes") or {}

    with st.expander("🏛️ Etapa 3 · Veredictos individuales de los 5 agentes", expanded=True):
        _tarjetas_agentes(aportes)
        if validacion.get("langsmith_url"):
            st.link_button(
                "🔗 Traza decidirCEO en LangSmith",
                validacion["langsmith_url"],
            )

    with st.expander("📝 Etapa 2 · Propuesta comercial redactada"):
        p1, p2, p3 = st.columns(3)
        p1.metric("Tier recomendado", propuesta.get("tier_recomendado"))
        rango = propuesta.get("rango_precio_clp") or [0, 0]
        p2.metric("Inversión CLP", f"{rango[0]:,} – {rango[1]:,}".replace(",", "."))
        t = propuesta.get("tiempo_estimado_semanas") or [0, 0]
        p3.metric("Plazo", f"{t[0]}–{t[1]} semanas")
        st.write(propuesta.get("propuesta_texto") or "")
        with st.expander("Propuesta interna enviada a decidirCEO"):
            st.json(propuesta.get("propuesta_interna_validada") or {})

seguimientos = st.session_state.fc_seguimientos
if seguimientos:
    st.subheader("🤝 Etapa 5 · Negociación (Seguimiento)")
    for idx, seg in enumerate(seguimientos, start=1):
        requiere_humano = bool(seg.get("requiere_intervencion_humana"))
        etiqueta_ronda = (
            f"Ronda {seg.get('ronda', idx)} · {seg.get('tipo_objecion', '?')}"
            + (" · ⤴ REQUIERE HUMANO" if requiere_humano else "")
        )
        with st.expander(etiqueta_ronda, expanded=(idx == len(seguimientos))):
            if requiere_humano:
                st.warning("Esta negociación quedó marcada para decisión humana.")
            ajuste = seg.get("ajuste_propuesto")
            if ajuste:
                a1, a2, a3 = st.columns(3)
                a1.metric("Tier ofertado", ajuste.get("tier"))
                ap = ajuste.get("precio_clp") or [0, 0]
                a2.metric("Precio CLP", f"{ap[0]:,} – {ap[1]:,}".replace(",", "."))
                ts = ajuste.get("tiempo_semanas") or [0, 0]
                a3.metric("Semanas", f"{ts[0]}–{ts[1]}")
            st.write(seg.get("respuesta_texto") or "")
            with st.expander("JSON de la ronda"):
                st.json(seg)

elif propuesta and activar_seg:
    st.caption(
        "💡 Activa el toggle de seguimiento, escribe la objeción del cliente "
        "y vuelve a pulsar 🚀 para procesarla sobre esta misma propuesta."
    )