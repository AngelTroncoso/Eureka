#!/usr/bin/env python3
"""
Pruebas del Agente de Propuestas Comerciales.

PARTE A (offline, sin red): integridad del catálogo, selección determinística
de tiers, pipeline completo mockeando redacción y validación CEO, y forma de
la propuesta interna tipo 'ventas'.
PARTE B (en vivo contra decidirCEO REAL vía scripts/e2e.js --json):
  · margen sano (30%)  → decisión 'aprobado'
  · margen bajo (20%)  → BLOQUEADO ('escalado_a_humano' por objeción Finanzas)

Uso:
    python tests/test_propuestas_comerciales.py [--solo-offline]
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RUTA_AGENTE = RAIZ / "src" / "agents" / "propuestas-comerciales.py"

_spec = importlib.util.spec_from_file_location("propuestas_comerciales", RUTA_AGENTE)
pc = importlib.util.module_from_spec(_spec)
sys.modules["propuestas_comerciales"] = pc
_spec.loader.exec_module(pc)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLAVES_SCHEMA = {
    "empresa",
    "tier_recomendado",
    "justificacion_tier",
    "rango_precio_clp",
    "tiempo_estimado_semanas",
    "propuesta_texto",
    "requiere_llamada_diagnostico",
    "fuente_catalogo",
}

FALLOS: list = []


def chequear(condicion: bool, mensaje: str) -> None:
    print(f"  {'OK ' if condicion else 'FALLO'} · {mensaje}")
    if not condicion:
        FALLOS.append(mensaje)


# ── Fixtures ──────────────────────────────────────────────────────────────────
DOSSIER_ALTA_TIER2 = {
    "empresa": "Comercial Andina SPA",
    "rubro": "Distribución mayorista",
    "tamano_estimado": "grande",
    "presencia_digital": {
        "sitio_web": "https://andina.cl",
        "linkedin": "https://www.linkedin.com/company/andina",
    },
    "senales_de_necesidad": [
        "Busca automatizar la gestión de pedidos con agentes de IA sobre sus datos internos",
        "Quiere un sistema multiagente para el seguimiento automático de cotizaciones",
        "La analítica de ventas se hace hoy en planillas manuales repetitivas",
    ],
    "fuentes": ["https://andina.cl"],
    "confianza": "alta",
}

DOSSIER_BAJA_CONF = {
    "empresa": "Taller Ruiz Ltda.",
    "rubro": "no encontrado",
    "tamano_estimado": "pyme",
    "presencia_digital": {"sitio_web": "no encontrado", "linkedin": "no encontrado"},
    "senales_de_necesidad": ["Creemos que nos serviría algo de inteligencia artificial"],
    "fuentes": [],
    "confianza": "baja",
}

DOSSIER_ENTERPRISE = {
    "empresa": "Grupo Vertice",
    "rubro": "Banca",
    "tamano_estimado": "grande",
    "presencia_digital": {"sitio_web": "https://vertice.cl", "linkedin": "no encontrado"},
    "senales_de_necesidad": [
        "Necesitan integración con su ERP legacy y migración parcial a cloud",
        "Requisitos de ciberseguridad y gobernanza para datos regulatorios",
    ],
    "fuentes": ["https://vertice.cl"],
    "confianza": "media",
}


# ─────────────────────────────────────────────────────────────────────────────
def parte_a_offline() -> None:
    print("\n== PARTE A · Offline: catálogo, selección y pipeline mock ==")

    catalogo = pc.cargar_catalogo()
    chequear([int(e["tier"]) for e in catalogo] == [1, 2, 3], "catálogo: tiers 1|2|3")
    chequear(
        all(e["precio_clp"][0] > 0 for e in catalogo if "precio_clp" in e),
        "catálogo: rangos de precio positivos",
    )

    # Selección determinística — caso objetivo: alta confianza ⇒ tier 2
    sel2 = pc.seleccionar_tier(DOSSIER_ALTA_TIER2, catalogo)
    chequear(
        sel2["tier_principal"] == 2,
        f"alta confianza + señales IA ⇒ tier 2 (obtuvo {sel2['tier_principal']})",
    )
    chequear(sel2["tiers"] == [2], f"tier único sin combinación (obtuvo {sel2['tiers']})")
    chequear(
        sel2["rango_precio_clp"] == [3000000, 8000000],
        "rango de precio EXACTO del catálogo (no inventado)",
    )
    chequear(
        sel2["requiere_llamada_diagnostico"] is False,
        "alta confianza ⇒ sin llamada obligatoria",
    )

    # Combinación hacia enterprise: señales de integración/ERP/cloud/seguridad
    sel3 = pc.seleccionar_tier(DOSSIER_ENTERPRISE, catalogo)
    chequear(
        sel3["tier_principal"] == 3,
        f"señales enterprise ⇒ tier 3 (obtuvo {sel3['tier_principal']})",
    )
    chequear(
        sel3["rango_precio_clp"] == [3000000, 10000000],
        "combinación 2+3: rango unión del catálogo",
    )

    # Confianza baja / pocas señales ⇒ diagnóstico primero
    sel_diag = pc.seleccionar_tier(DOSSIER_BAJA_CONF, catalogo)
    chequear(
        sel_diag["requiere_llamada_diagnostico"] is True,
        "confianza baja ⇒ requiere_llamada_diagnostico=True",
    )
    chequear(
        "diagnóstico" in sel_diag["justificacion_tier"].lower(),
        "justificación declara explícitamente el diagnóstico",
    )

    # Propuesta interna tipo 'ventas': forma y paso del margen
    interna = pc._construir_propuesta_interna(DOSSIER_ALTA_TIER2, sel2, 20)
    chequear(
        interna["agente"] == "ventas" and interna["tipo"] == "propuesta",
        "interna: agente=ventas, tipo=propuesta (reutiliza flujo existente)",
    )
    chequear(
        interna["datos_clave"]["margen_bruto"] == 20,
        "interna: el margen estimado viaja a decidirCEO",
    )

    # Pipeline completo con redacción y CEO mockeados
    texto_modelo = "Estimados, tras revisar sus procesos proponemos… (demo)"
    orig_redactar = pc._redactar_texto_gemini
    orig_validar = pc.validar_con_decidir_ceo
    try:
        pc._redactar_texto_gemini = lambda cliente, prompt: texto_modelo
        pc.validar_con_decidir_ceo = lambda p_interna: {
            "decision": "aprobado",
            "lista_para_enviar": True,
            "detalle": "ok (mock)",
            "run_id": "mock-run-id",
            "langsmith_url": None,
        }
        salida = pc.crear_propuesta(DOSSIER_ALTA_TIER2)
    finally:
        pc._redactar_texto_gemini = orig_redactar
        pc.validar_con_decidir_ceo = orig_validar

    chequear(CLAVES_SCHEMA.issubset(set(salida)), "pipeline mock: las 8 claves del esquema presentes")
    chequear(
        salida["tier_recomendado"] == 2
        and salida["fuente_catalogo"] == "config/catalogo-servicios.json",
        "pipeline mock: tier y fuente correctos",
    )
    chequear(
        salida["validacion_ceo"]["decision"] == "aprobado"
        and salida["lista_para_enviar"] is True,
        "pipeline mock: aprobado ⇒ lista_para_enviar",
    )


# ─────────────────────────────────────────────────────────────────────────────
def parte_b_decidir_ceo_real() -> None:
    print("\n== PARTE B · Validación EN VIVO contra decidirCEO() real ==")

    catalogo = pc.cargar_catalogo()
    sel_ok = pc.seleccionar_tier(DOSSIER_ALTA_TIER2, catalogo)

    print("\n— Caso sano (margen 30%):")
    sana = pc._construir_propuesta_interna(DOSSIER_ALTA_TIER2, sel_ok, 30)
    res_ok = pc.validar_con_decidir_ceo(sana)
    chequear(res_ok["decision"] == "aprobado", f"decisión = {res_ok['decision']}")
    chequear(res_ok["lista_para_enviar"] is True, "lista_para_enviar=True")

    print("\n— Caso bloqueado (margen 20% < objetivo 25%):")
    mala = pc._construir_propuesta_interna(DOSSIER_ALTA_TIER2, sel_ok, 20)
    res_mala = pc.validar_con_decidir_ceo(mala)
    chequear(
        res_mala["decision"] == "escalado_a_humano",
        f"BLOQUEADA por margen ⇒ {res_mala['decision']}",
    )
    detalle_bajo = str(res_mala.get("detalle", "")).lower()
    chequear(
        "finanzas" in detalle_bajo and "margen" in detalle_bajo,
        "objeción citada proviene de Finanzas (margen)",
    )
    chequear(res_mala["lista_para_enviar"] is False, "lista_para_enviar=False")


if __name__ == "__main__":
    parte_a_offline()
    if "--solo-offline" not in sys.argv:
        parte_b_decidir_ceo_real()

    print("\n================ RESULTADO ================")
    if FALLOS:
        print(f"FALLOS ({len(FALLOS)}):")
        for f in FALLOS:
            print(" -", f)
        sys.exit(1)
    print("TODOS LOS CHEQUEOS PASARON")