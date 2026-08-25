#!/usr/bin/env python3
"""
EUREKA · Interfaz Streamlit del CEO Agent Orchestrator.

DISPARA el flujo agéntico real (TypeScript/Node + Python/Gemini) y visualiza
sus resultados y su traza LangSmith. NO reimplementa lógica de decisión.

Uso:
    streamlit run app_streamlit.py

El script Node que se invoca es scripts/e2e.js --json que devuelve un ÚNICO
objeto JSON por stdout (todo el resto va a stderr), por lo que esta UI solo
tiene que parsear JSON.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------------
# Configuración de la página
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="EUREKA CEO Orchestrator",
    page_icon="🤖",
    layout="wide",
)

# Rutas ANCLADAS al archivo del script (no al cwd desde donde se lance
# streamlit): Path(__file__).resolve() sigue symlinks y convierte rutas
# relativas en absolutas usando SIEMPRE la ubicación real de este archivo.
BASE_DIR = Path(__file__).resolve().parent
SCRIPT_E2E = BASE_DIR / "scripts" / "e2e.js"
ARCHIVO_EJEMPLOS = BASE_DIR / "examples" / "propuestas.json"
RAIZ = BASE_DIR  # alias de compatibilidad

MAX_HISTORIAL = 20  # últimas N decisiones en la sesión

# ----------------------------------------------------------------------------
# Esquema de colores consistente (misma severidad en todas las vistas)
# ----------------------------------------------------------------------------
COLOR_SEVERIDAD = {
    "critica": "#c62828",      # rojo
    "advertencia": "#ef6c00",  # ámbar/naranja
    "sugerencia": "#2e7d32",   # verde
}
COLOR_DECISION = {
    "aprobado": "#2e7d32",          # verde
    "rechazado": "#c62828",         # rojo
    "reformular": "#ef6c00",        # ámbar
    "escalado_a_humano": "#ed6c02", # naranja
}
ETIQUETA_DECISION = {
    "aprobado": "√ APROBADO",
    "rechazado": "✗ RECHAZADO",
    "reformular": "↻ REFORMULAR",
    "escalado_a_humano": "⤴ ESCALADO",
}

NOMBRES_AGENTES = {
    "finanzas": "Finanzas",
    "logistica": "Logística",
    "compras": "Compras",
    "ventas": "Ventas",
    "ventas-observador": "Ventas-Observador",
    "gemini": "Gemini (IA)",
}

AGENTES_BASE = ("finanzas", "logistica", "compras", "ventas")


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def cargar_propuestas_ejemplo() -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Lee examples/propuestas.json y devuelve (propuestas, diagnostico).

    'diagnostico' es None cuando todo fue bien; en cualquier otro caso es un
    mensaje que incluye la RUTA ABSOLUTA EXACTA intentada y el motivo del
    fallo, para poder diagnosticarlo desde la propia interfaz.
    """
    ruta = str(ARCHIVO_EJEMPLOS)

    # Verificación explícita ANTES de abrir el archivo.
    if not os.path.exists(ruta):
        return [], (
            "El archivo de propuestas NO existe.\n"
            f"Ruta absoluta intentada: {ruta}\n"
            f"BASE_DIR del script: {BASE_DIR}"
        )
    if not os.path.isfile(ruta):
        return [], f"La ruta existe pero no es un archivo: {ruta}"

    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except json.JSONDecodeError as exc:
        return [], (
            "El archivo existe pero NO es JSON válido.\n"
            f"Ruta: {ruta}\n"
            f"Detalle: {exc}"
        )
    except OSError as exc:
        return [], (
            "No se pudo abrir el archivo (¿placeholder de OneDrive sin "
            "descargar? → clic derecho › «Mantener siempre en este "
            "dispositivo»; ¿permisos?).\n"
            f"Ruta: {ruta}\n"
            f"Detalle: {exc}"
        )

    if not isinstance(datos, dict) or not isinstance(datos.get("propuestas"), list):
        return [], (
            "Estructura inesperada: se esperaba {\"propuestas\": [...]}\n"
            f"Ruta: {ruta}"
        )

    propuestas = [p for p in datos["propuestas"] if isinstance(p, dict)]
    if not propuestas:
        return [], f"El archivo no contiene propuestas utilizables.\nRuta: {ruta}"

    return propuestas, None


def ejecutar_flujo_ceo(
    propuesta: Dict[str, Any], con_gemini: bool
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Dispara el flujo agéntico real: node scripts/e2e.js --json [gemini].

    La propuesta viaja por la variable de entorno EUREKA_PROPUESTA_JSON.
    Devuelve (payload, error): exactamente uno de los dos es None.
    """
    env = os.environ.copy()
    env["EUREKA_PROPUESTA_JSON"] = json.dumps(propuesta, ensure_ascii=False)

    comando = ["node", str(SCRIPT_E2E), "--json"]
    if con_gemini:
        comando.append("gemini")

    try:
        proc = subprocess.run(
            comando,
            cwd=RAIZ,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,  # la llamada al agente Gemini puede tardar varios minutos
        )
    except subprocess.TimeoutExpired:
        return None, "El flujo agéntico excedió el tiempo máximo de 10 minutos."
    except OSError as exc:
        return None, f"No se pudo ejecutar Node.js ({SCRIPT_E2E}): {exc}"

    # En modo --json stdout contiene UN ÚNICO objeto JSON; los logs van a stderr.
    salida = (proc.stdout or "").strip()
    payload: Optional[Dict[str, Any]] = None
    inicio = salida.find("{")
    if inicio != -1:
        try:
            cargado = json.loads(salida[inicio:])
            if isinstance(cargado, dict):
                payload = cargado
        except json.JSONDecodeError:
            payload = None

    if payload is None:
        detalle = ((proc.stderr or "").strip()[-1500:]) or "(sin salida en stderr)"
        return None, (
            f"scripts/e2e.js terminó con código {proc.returncode} sin devolver "
            f"JSON válido.\n\n--- stderr ---\n{detalle}"
        )
    return payload, None


def etiqueta_agente(nombre: str) -> str:
    """Nombre legible de un agente ('finanzas' → 'Finanzas')."""
    return NOMBRES_AGENTES.get(nombre, nombre)


def icono_validacion(valida: Optional[bool]) -> str:
    """Icono consistente para el resultado de validación de un agente."""
    return "✅" if valida else ("❌" if valida is False else "•")


def fila_historial(registro: Dict[str, Any]) -> Dict[str, str]:
    """Aplana un registro de sesión a una fila del DataFrame de historial."""
    payload = registro["payload"]
    decision = str(payload.get("decision", "")).lower()
    return {
        "Hora": registro["fecha"].strftime("%H:%M:%S"),
        "Agente": registro["propuesta"].get("agente", "?"),
        "Resumen": registro["propuesta"].get("resumen", ""),
        "Decisión": ETIQUETA_DECISION.get(decision, decision or "?"),
        "Riesgo": registro["propuesta"].get("riesgo", "—"),
        "Gemini": "sí" if registro["con_gemini"] else "no",
        "run_id": payload.get("run_id") or "",
        "Traza": payload.get("langsmith_url") or "",
    }


# ----------------------------------------------------------------------------
# Estado de sesión
# ----------------------------------------------------------------------------
if "historial" not in st.session_state:
    st.session_state.historial = []   # últimas decisiones de esta sesión
if "ultimo" not in st.session_state:
    st.session_state.ultimo = None    # última ejecución completa

PROPUESTAS, DIAG_PROPUESTAS = cargar_propuestas_ejemplo()

# ----------------------------------------------------------------------------
# Barra lateral: selección de propuesta y disparo del flujo
# ----------------------------------------------------------------------------
with st.sidebar:
    st.header("🤖 EUREKA")
    st.caption("Orquestador del CEO · trazas en LangSmith")

    if PROPUESTAS:
        indice = st.selectbox(
            "Propuesta de entrada",
            options=list(range(len(PROPUESTAS))),
            format_func=lambda i: (
                f"{PROPUESTAS[i].get('agente', '?')} · {PROPUESTAS[i].get('resumen', '')}"
            ),
        )
        propuesta_actual = PROPUESTAS[indice]
        with st.expander("Ver JSON de la propuesta"):
            st.json(propuesta_actual)
    else:
        propuesta_actual = None
        st.error(
            "⚠️ No se pudieron cargar las propuestas de ejemplo.\n\n"
            f"{DIAG_PROPUESTAS}"
        )

    con_gemini = st.toggle(
        "Incluir agente Gemini (Python)",
        value=False,
        help="Lanza además eureka_agent_bridge.py como span anidado en la traza.",
    )

    lanzar = st.button(
        "▶ Ejecutar decisión del CEO",
        type="primary",
        use_container_width=True,
        disabled=propuesta_actual is None,
    )

    st.divider()
    st.metric("Decisiones en la sesión", len(st.session_state.historial))
    st.caption(f"Se conservan las últimas {MAX_HISTORIAL}")


# ----------------------------------------------------------------------------
# Cabecera principal
# ----------------------------------------------------------------------------
st.title("📊 Decisión del CEO — EUREKA")
st.caption(
    "Esta interfaz DISPARA el flujo agéntico real (TypeScript/Node + Python/Gemini) "
    "y visualiza su resultado y su traza LangSmith. No reimplementa lógica de decisión."
)


# ----------------------------------------------------------------------------
# Ejecución del flujo
# ----------------------------------------------------------------------------
if lanzar and propuesta_actual is not None:
    with st.spinner(
        "Ejecutando los 5 agentes TypeScript"
        + (" + agente Gemini (Python)" if con_gemini else "")
        + " y publicando la traza en LangSmith…"
    ):
        payload_nuevo, error = ejecutar_flujo_ceo(propuesta_actual, con_gemini)

    if error is not None:
        st.session_state.ultimo = None
        st.error("La ejecución del flujo agéntico falló.")
        with st.expander("Detalle técnico (stderr)"):
            st.code(error, language=None)
    else:
        st.session_state.ultimo = {
            "fecha": datetime.now(),
            "propuesta": propuesta_actual,
            "con_gemini": con_gemini,
            "payload": payload_nuevo or {},
        }
        st.session_state.historial.insert(0, st.session_state.ultimo)
        del st.session_state.historial[MAX_HISTORIAL:]
        st.rerun()


# ----------------------------------------------------------------------------
# Visualización de la última decisión
# ----------------------------------------------------------------------------
registro = st.session_state.ultimo
if registro is None:
    st.info(
        "👈 Selecciona una propuesta en la barra lateral y pulsa "
        "**▶ Ejecutar decisión del CEO** para arrancar el ciclo completo."
    )
    st.stop()

payload = registro["payload"]
propuesta = registro["propuesta"]
decision = str(payload.get("decision", "")).lower()
color_dec = COLOR_DECISION.get(decision, "#455a64")
etiqueta = ETIQUETA_DECISION.get(decision, decision.upper() or "—")

st.markdown(
    f"""
    <div style="padding:1rem 1.25rem;border-radius:.6rem;background:{color_dec};
                box-shadow:0 1px 4px rgba(0,0,0,.15);margin-bottom:.25rem;">
      <span style="font-size:.8rem;color:rgba(255,255,255,.85);letter-spacing:.14em;">
        DECISIÓN DEL CEO</span>
      <h2 style="color:#ffffff;margin:.15rem 0 0;">{etiqueta}</h2>
    </div>
    """,
    unsafe_allow_html=True,
)
st.caption(
    f"{registro['fecha'].strftime('%d/%m/%Y %H:%M:%S')} · propuesta de "
    f"{etiqueta_agente(str(propuesta.get('agente', '')))} · "
    f"{'con' if registro['con_gemini'] else 'sin'} agente Gemini"
)

run_id = payload.get("run_id") or ""
c1, c2, c3, c4 = st.columns(4)
c1.metric("Riesgo declarado", str(propuesta.get("riesgo", "—")))
c2.metric("Agentes consultados", len(payload.get("aportes_agentes") or {}))
c3.metric("Agente Gemini", "✓ ejecutado" if payload.get("aportes_gemini") else "omitido")
c4.metric("Run LangSmith", (run_id[:8] + "…") if run_id else "sin tracing")

izquierda, derecha = st.columns((3, 2))
with izquierda:
    st.subheader("Justificación")
    st.write(payload.get("justificacion") or "—")
    if payload.get("trade_off"):
        st.markdown(f"⚖️ **Trade-off declarado:** {payload['trade_off']}")
with derecha:
    st.subheader("Trazabilidad")
    url_traza = payload.get("langsmith_url")
    if url_traza:
        st.link_button("🔗 Abrir traza en LangSmith", url_traza, use_container_width=True)
    elif run_id:
        st.warning("Sin enlace directo; búscalo en LangSmith con este run:")
        st.code(run_id, language=None)
    else:
        st.info("Sin tracing: revisa LANGCHAIN_* en .env")

st.divider()

# ----------------------------------------------------------------------------
# Aportes de los agentes base (finanzas / logistica / compras / ventas)
# ----------------------------------------------------------------------------
st.subheader("Aportes de los agentes")
aportes = payload.get("aportes_agentes") or {}

tarjetas = st.columns(len(AGENTES_BASE))
for col, nombre in zip(tarjetas, AGENTES_BASE):
    aporte = aportes.get(nombre) or {}
    with col.container(border=True):
        col.markdown(f"**{etiqueta_agente(nombre)}**")
        col.markdown(
            f"{icono_validacion(aporte.get('valida'))} {aporte.get('mensaje') or '—'}"
        )

# ----------------------------------------------------------------------------
# Ventas-observador (evaluación estratégica con severidad y recomendación)
# ----------------------------------------------------------------------------
observador = aportes.get("ventas-observador")
if observador:
    severidad = str(observador.get("severidad", "")).lower()
    color_sev = COLOR_SEVERIDAD.get(severidad, "#455a64")
    with st.container(border=True):
        cab1, cab2 = st.columns((2, 3))
        cab1.markdown("**👁 Ventas-Observador**")
        cab2.markdown(
            f"<span style='color:{color_sev};font-weight:700'>● "
            f"{severidad or 'sin severidad'}</span> &nbsp;·&nbsp; "
            f"recomendación al CEO: <code>{observador.get('recomendacionAlCeo', '—')}</code>",
            unsafe_allow_html=True,
        )
        st.write(observador.get("evaluacion") or "")
        r_riesgos, r_conflictos, r_mejoras = st.columns(3)
        r_riesgos.markdown("**⚠️ Riesgos detectados**")
        for riesgo in observador.get("riesgos") or []:
            r_riesgos.markdown(f"- {riesgo}")
        r_conflictos.markdown("**⚔️ Conflictos con**")
        for conflicto in observador.get("conflictosCon") or []:
            r_conflictos.markdown(f"- {etiqueta_agente(str(conflicto))}")
        r_mejoras.markdown("**💡 Mejoras propuestas**")
        for mejora in observador.get("mejorasPropuestas") or []:
            r_mejoras.markdown(f"- {mejora}")

# ----------------------------------------------------------------------------
# Agente Gemini (subproceso Python, opcional)
# ----------------------------------------------------------------------------
gemini = payload.get("aportes_gemini")
if gemini:
    st.subheader("🧠 Agente Gemini (IA)")
    if gemini.get("error"):
        st.error(f"El subproceso de Gemini reportó un error:\n\n{gemini['error']}")
    else:
        g_val, g_ctx = st.columns(2)
        with g_val.container(border=True):
            st.markdown("**Validación financiera**")
            st.json(gemini.get("validation") or {})
        with g_ctx.container(border=True):
            st.markdown("**Contexto EUREKA utilizado**")
            st.text(gemini.get("context") or "—")

# ----------------------------------------------------------------------------
# Historial de decisiones de la sesión
# ----------------------------------------------------------------------------
st.divider()
cab_hist, btn_hist = st.columns((3, 1))
cab_hist.subheader("🗂 Historial de la sesión")
if st.session_state.historial:
    df_historial = pd.DataFrame(
        [fila_historial(r) for r in st.session_state.historial]
    )
    st.dataframe(
        df_historial,
        hide_index=True,
        width="stretch",
        column_config={
            "Traza": st.column_config.LinkColumn("Traza", display_text="🔗 abrir"),
            "run_id": st.column_config.TextColumn("run_id"),
        },
    )
    if btn_hist.button("🧹 Limpiar historial"):
        st.session_state.historial.clear()
        st.session_state.ultimo = None
        st.rerun()
else:
    st.caption("Aún no hay decisiones registradas en esta sesión.")