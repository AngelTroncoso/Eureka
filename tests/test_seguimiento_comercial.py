#!/usr/bin/env python3
"""
Pruebas del Agente de Seguimiento Comercial.

PARTE A (offline, con decidirCEO y Gemini mockeados): clasificador de
objeciones, pisos duros de tier, límite de rondas, fuera-de-catálogo y
cierres por aceptación/rechazo.
PARTE B (en vivo): un ajuste aprobado pasando por decidirCEO() REAL.

Uso:
    python tests/test_seguimiento_comercial.py [--solo-offline]
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RUTA_AGENTE = RAIZ / "src" / "agents" / "seguimiento-comercial.py"

_spec = importlib.util.spec_from_file_location("seguimiento_comercial", RUTA_AGENTE)
sc = importlib.util.module_from_spec(_spec)
sys.modules["seguimiento_comercial"] = sc
_spec.loader.exec_module(sc)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FALLOS: list = []


def chequear(condicion: bool, mensaje: str) -> None:
    print(f"  {'OK ' if condicion else 'FALLO'} · {mensaje}")
    if not condicion:
        FALLOS.append(mensaje)


# ── Fixture: salida típica de propuestas-comerciales.py (tier 2 aprobado) ───
PROPUESTA = {
    "empresa": "Comercial Andina SPA",
    "tier_recomendado": 2,
    "rango_precio_clp": [3000000, 8000000],
    "tiempo_estimado_semanas": [6, 10],
    "requiere_llamada_diagnostico": False,
    "fuente_catalogo": "config/catalogo-servicios.json",
    "propuesta_texto": "Propuesta Multiagente a Medida…",
    "validacion_ceo": {
        "decision": "aprobado",
        "lista_para_enviar": True,
        "detalle": "Propuesta validada por los 5 agentes.",
        "run_id": "ceo-run-origen-123",
        "langsmith_url": "https://smith.langchain.com/ejemplo/r/ceo-run-origen-123",
    },
    "propuesta_interna_validada": {
        "agente": "ventas",
        "tipo": "propuesta",
        "datos_clave": {
            "margen_bruto": 30,
            "monto": 8000000,
            "tier": 2,
            "empresa_prospecto": "Comercial Andina SPA",
        },
        "resumen": "Propuesta comercial tier 2 para Comercial Andina SPA",
        "riesgo": "medio",
        "requiere_aprobacion_ceo": True,
    },
}

CLAVES_SCHEMA = {
    "empresa",
    "ronda",
    "tipo_objecion",
    "ajuste_propuesto",
    "validacion_ceo",
    "requiere_intervencion_humana",
    "respuesta_texto",
    "historial_ronda",
}


def _con_mocks_validacion_aprobada():
    """Contexto simple: parchea CEO (aprobado) y Gemini; devuelve restaurador."""
    llamadas_ceo = {"n": 0}
    orig_validar = pc_module().validar_con_decidir_ceo
    orig_redactar = sc._redactar_respuesta_gemini

    def validar_falso(p_interna):
        llamadas_ceo["n"] += 1
        return {
            "decision": "aprobado",
            "lista_para_enviar": True,
            "detalle": "aprobado (mock)",
            "run_id": "ceo-mock",
            "langsmith_url": None,
        }

    pc_module().validar_con_decidir_ceo = validar_falso
    sc._redactar_respuesta_gemini = lambda cliente, prompt: "RESPUESTA MOCK"

    def restaurar():
        pc_module().validar_con_decidir_ceo = orig_validar
        sc._redactar_respuesta_gemini = orig_redactar

    return restaurar, llamadas_ceo


def pc_module():
    """Acceso al módulo de propuestas reutilizado por seguimiento."""
    return sys.modules["propuestas_comerciales"]


# ─────────────────────────────────────────────────────────────────────────────
def parte_a_offline() -> None:
    print("\n== PARTE A · Offline: clasificador, pisos duros y límites ==")

    # ── Clasificador ──
    casos = {
        "Perfecto, avanzamos entonces": "aceptacion",
        "Lamentablemente no vamos a avanzar con esto": "rechazo_definitivo",
        "El precio nos queda caro, ¿hay descuento?": "precio",
        "¿En cuántas semanas estaría listo? Es urgente": "tiempo",
        "Buscamos algo de menos alcance, más simple": "alcance",
        "¿Y si además desarrollan la app móvil nativa de nuestro cliente?": "otra",
    }
    for texto, esperado in casos.items():
        chequear(sc.clasificar_objecion(texto) == esperado, f"clasifica '{texto[:38]}…' ⇒ {esperado}")

    restaurar, llamadas = _con_mocks_validacion_aprobada()
    try:
        # ── Precio DENTRO del rango del tier 2 ──
        r = sc.negociar_ronda(PROPUESTA, "¿Pueden dejarlo en 5.000.000?", ronda=1)
        chequear(r["tipo_objecion"] == "precio", "objeción clasificada como 'precio'")
        chequear(
            r["ajuste_propuesto"]["tier"] == 2
            and r["ajuste_propuesto"]["precio_clp"] == [5000000, 5000000],
            "ajuste DENTRO del rango: tier 2 @ $5.000.000",
        )
        chequear(r["requiere_intervencion_humana"] is False and r["validacion_ceo"]["decision"] == "aprobado", "ajuste validado por CEO mock ⇒ sin intervención")
        chequear(CLAVES := {"empresa","ronda","tipo_objecion","ajuste_propuesto","validacion_ceo","requiere_intervencion_humana","respuesta_texto","historial_ronda"}.issubset(set(r)), "esquema de salida completo")
        chequear(
            r["referencia_propuesta_origen"]["run_id_ceo"] == "ceo-run-origen-123",
            "referencia al run CEO de la propuesta origen",
        )

        # ── Precio BAJO el mínimo del tier 2 ⇒ BAJA a tier 1 ──
        r = sc.negociar_ronda(PROPUESTA, "Solo tenemos 1.500.000 de presupuesto", ronda=1)
        chequear(
            r["ajuste_propuesto"]["tier"] == 1
            and r["ajuste_propuesto"]["precio_clp"] == [1500000, 1500000],
            "pedido $1.5M < piso tier2 ⇒ baja a tier 1 @ $1.5M (dentro de su rango)",
        )

        # ── Precio bajo TODO piso ⇒ contraoferta en el mínimo del tier 1 ──
        r = sc.negociar_ronda(PROPUESTA, "Como máximo podemos poner 500.000", ronda=1)
        chequear(
            r["ajuste_propuesto"]["tier"] == 1
            and r["ajuste_propuesto"]["precio_clp"] == [800000, 800000],
            "pedido $0.5M bajo todos los pisos ⇒ contraoferta piso tier 1 ($800.000)",
        )

        # ── Tiempo urgente bajo el mínimo del tier 2 ⇒ baja a tier 1 ──
        r = sc.negociar_ronda(PROPUESTA, "Lo necesito en 3 semanas como máximo", ronda=1)
        chequear(
            r["ajuste_propuesto"]["tier"] == 1
            and r["ajuste_propuesto"]["tiempo_semanas"] == [3, 3],
            "plazo 3 sem < mínimo tier2 (6) ⇒ baja a tier 1 (mín 2) @ 3 semanas",
        )

        # ── Alcance menor ⇒ baja un tier con rangos completos ──
        r = sc.negociar_ronda(PROPUESTA, "Preferimos algo de menos alcance para empezar", ronda=1)
        chequear(
            r["ajuste_propuesto"]["tier"] == 1
            and r["ajuste_propuesto"]["precio_clp"] == [800000, 2000000]
            and r["ajuste_propuesto"]["tiempo_semanas"] == [2, 4],
            "menos alcance ⇒ tier 1 completo (rangos literales del catálogo)",
        )
    finally:
        restaurar()

    # ── Límite DURO: ronda 3 sin acuerdo ⇒ intervención humana ──
    r3 = sc.negociar_ronda(PROPUESTA, "Sigue carísimo, no puedo pagar eso", ronda=3)
    chequear(r3["requiere_intervencion_humana"] is True, "ronda 3 sin acuerdo ⇒ intervención humana")
    chequear(r3["ajuste_propuesto"] is None and r3["validacion_ceo"] is None, "ronda 3: SIN nuevo ajuste ni validación")
    chequear(len(r3["historial_ronda"]) >= 1, "resumen de negociación presente en historial")

    # ── Fuera de catálogo ('otra') ⇒ intervención INMEDIATA sin llamar al CEO ──
    restaurar_otra, llamadas_otra = _con_mocks_validacion_aprobada()
    try:
        r_otra = sc.negociar_ronda(
            PROPUESTA,
            "¿Y si además desarrollan la app móvil nativa para nuestros repartidores?",
            ronda=1,
        )
    finally:
        restaurar_otra()
    chequear(r_otra["tipo_objecion"] == "otra", "clasificada como 'otra'")
    chequear(r_otra["requiere_intervencion_humana"] is True, "'otra' ⇒ intervención humana INMEDIATA")
    chequear(r_otra["ajuste_propuesto"] is None and r_otra["validacion_ceo"] is None, "'otra': sin ajuste ni validación (nada improvisado)")
    chequear(llamadas_otra["n"] == 0, "'otra' NO llamó a decidirCEO (0 llamadas)")

    # ── Aceptación ⇒ cierre administrativo ──
    restaurar_acep, _ = _con_mocks_validacion_aprobada()
    try:
        r_acep = sc.negociar_ronda(PROPUESTA, "Me parece bien, aceptamos la propuesta", ronda=1)
    finally:
        restaurar_acep()
    chequear(r_acep["tipo_objecion"] == "aceptacion" and r_acep["requiere_intervencion_humana"] is False, "aceptación ⇒ cierre cordial sin intervención")


# ─────────────────────────────────────────────────────────────────────────────
def parte_b_decidir_ceo_real() -> None:
    print("\n== PARTE B · Ajuste aprobado vía decidirCEO() REAL ==")

    catalogo = pc_module().cargar_catalogo()
    estado = {
        "tier": 1,
        "precio_clp": [800000, 2000000],
        "tiempo_semanas": [2, 4],
        "margen": 30.0,
        "historial": [],
    }
    decision = sc.calcular_ajuste(
        "precio", "¿Lo dejamos en 1.000.000?", estado, catalogo
    )
    ajuste = decision["ajuste_propuesto"]
    chequear(
        ajuste["precio_clp"] == [1000000, 1000000],
        f"ajuste calculado a ${ajuste['precio_clp'][0]}",
    )

    seleccion = {
        "tier_principal": ajuste["tier"],
        "nombres": ajuste.get("nombre_tier", ""),
        "entradas": [pc_module()._entrada_tier(catalogo, ajuste["tier"])],
        "rango_precio_clp": ajuste["precio_clp"],
        "tiempo_estimado_semanas": ajuste["tiempo_semanas"],
        "requiere_llamada_diagnostico": False,
    }
    interna = pc_module()._construir_propuesta_interna(
        {"empresa": "Cliente Demo"}, seleccion, 30
    )
    res = pc_module().validar_con_decidir_ceo(interna)
    chequear(
        res["decision"] == "aprobado" and res["lista_para_enviar"] is True,
        f"decidirCEO REAL aprobó el ajuste ({res['decision']}) · run {res.get('run_id')}",
    )


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