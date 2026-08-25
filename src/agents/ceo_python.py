#!/usr/bin/env python3
"""
EUREKA · Motor de decisión decidirCEO en PYTHON PURO (fallback sin Node).

Réplica 1:1 de las reglas de src/core/ceo.ts y los agentes TypeScript
(finanzas/logistica/compras/ventas/ventas-observador + company.ts).
Existe porque Streamlit Community Cloud no dispone de Node.js ni de los
artefactos compilados (dist/, node_modules): cuando el subproceso
scripts/e2e.js no puede ejecutarse, este módulo aplica EXACTAMENTE las
mismas reglas deterministas en Python.

REGLAS (orden idéntico a ceo.ts):
  1. Caja disponible: impacto sobre caja_actual no puede caer bajo $50M.
  2. Validación del agente ORIGEN inválida → rechazado.
  3. Escalamiento: monto > $100M o (riesgo alto Y riesgo legal).
  4. Cruce con otras propuestas → reformular.
  5. VETO CRUZADO: objeción de cualquier agente base o alerta crítica del
     ventas-observador → escalado_a_humano.
  6. La recomendación del ventas-observador nunca se ignora
     (escalar → escalado; solicitar_ajustes → reformular).
Si nada aplica → 'aprobado'.

Salida: mismo formato que scripts/e2e.js --json (decision, justificacion,
trade_off, aportes_agentes como mapa agente→resultado), para que la UI y los
consumidores existentes no requieran cambios.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── Contexto de empresa (src/config/company.ts) ──────────────────────────────
CONTEXTO_EUREKA: Dict[str, Any] = {
    "objetivo_trimestral": {"margen_bruto": 25, "crecimiento_ventas": 15},
    "restricciones": {
        "caja_minima": 50_000_000,
        "limite_deuda": 200_000_000,
        "max_porcentaje_caja_proyecto": 30,
    },
    "umbral_escalamiento": {
        "monto": 100_000_000,
        "riesgos_legales": True,
        "conflictos_irresolubles": True,
    },
}

_VARIACION_MAXIMA_COMPRAS = 0.15  # compras.ts


def _num(datos: Dict[str, Any], clave: str) -> Optional[float]:
    valor = datos.get(clave)
    return None if valor is None else float(valor)


# ── Agentes base (réplica exacta de cada *.ts) ───────────────────────────────
def _validar_finanzas(p: Dict[str, Any]) -> Dict[str, Any]:
    d = p.get("datos_clave") or {}
    margen = _num(d, "margen_bruto")
    objetivo = CONTEXTO_EUREKA["objetivo_trimestral"]["margen_bruto"]
    if margen is not None and margen < objetivo:
        return {
            "valida": False,
            "mensaje": (
                f"Margen bruto {d.get('margen_bruto')}% es inferior al "
                f"objetivo trimestral de {objetivo}%"
            ),
        }
    caja = _num(d, "caja_proyectada")
    caja_minima = CONTEXTO_EUREKA["restricciones"]["caja_minima"]
    if caja is not None and caja < caja_minima:
        return {
            "valida": False,
            "mensaje": (
                f"Caja proyectada ${d.get('caja_proyectada')} es inferior a "
                f"la mínima de ${caja_minima}"
            ),
        }
    if d.get("deuda_propuesta") is not None:
        deuda_actual = _num(d, "deuda_actual") or 0.0
        limite = CONTEXTO_EUREKA["restricciones"]["limite_deuda"]
        if deuda_actual + float(d["deuda_propuesta"]) > limite:
            return {
                "valida": False,
                "mensaje": (
                    f"Deuda propuesta ${d.get('deuda_propuesta')} supera el "
                    f"límite de ${limite}"
                ),
            }
    return {"valida": True, "mensaje": "Propuesta válida desde la perspectiva financiera"}


def _validar_logistica(p: Dict[str, Any]) -> Dict[str, Any]:
    d = p.get("datos_clave") or {}
    if d.get("stock_solicitado") is not None:
        capacidad_actual = _num(d, "capacidad_actual") or 0.0
        capacidad_maxima = _num(d, "capacidad_maxima")
        capacidad_maxima = capacidad_actual if capacidad_maxima is None else capacidad_maxima
        if capacidad_actual + float(d["stock_solicitado"]) > capacidad_maxima:
            return {
                "valida": False,
                "mensaje": (
                    f"Stock solicitado {d.get('stock_solicitado')} supera la "
                    f"capacidad máxima de {capacidad_maxima}"
                ),
            }
    if d.get("plazo_entrega") is not None:
        plazo_maximo = _num(d, "plazo_maximo") or 30.0
        if float(d["plazo_entrega"]) > plazo_maximo:
            return {
                "valida": False,
                "mensaje": (
                    f"Plazo de entrega {d.get('plazo_entrega')} días supera "
                    f"el máximo de {plazo_maximo} días"
                ),
            }
    return {"valida": True, "mensaje": "Propuesta válida desde la perspectiva logística"}


def _validar_compras(p: Dict[str, Any]) -> Dict[str, Any]:
    d = p.get("datos_clave") or {}
    precio_compra = _num(d, "precio_compra")
    precio_mercado = _num(d, "precio_mercado")
    if precio_compra is not None and precio_mercado is not None:
        if precio_compra > precio_mercado * (1 + _VARIACION_MAXIMA_COMPRAS):
            return {
                "valida": False,
                "mensaje": (
                    f"Precio de compra ${d.get('precio_compra')} supera el "
                    f"precio de mercado en más del 15%"
                ),
            }
    calidad = d.get("calidad_proveedor")
    if calidad is not None and float(calidad) < 3:
        return {
            "valida": False,
            "mensaje": (
                f"Calidad del proveedor {calidad}/5 es insuficiente (mínimo 3/5)"
            ),
        }
    return {"valida": True, "mensaje": "Propuesta válida desde la perspectiva de compras"}


def _validar_ventas(p: Dict[str, Any]) -> Dict[str, Any]:
    d = p.get("datos_clave") or {}
    margen = _num(d, "margen_bruto")
    if margen is not None and margen < 0:
        return {
            "valida": False,
            "mensaje": (
                f"margen bruto negativo {d.get('margen_bruto')}% viola el valor "
                f"no negociable de no vender bajo costo"
            ),
        }
    crecimiento = _num(d, "crecimiento_ventas")
    if crecimiento is not None:
        objetivo = CONTEXTO_EUREKA["objetivo_trimestral"]["crecimiento_ventas"]
        crecimiento_minimo = objetivo * 0.8
        if crecimiento < crecimiento_minimo:
            return {
                "valida": False,
                "mensaje": (
                    f"Crecimiento de ventas {d.get('crecimiento_ventas')}% es "
                    f"inferior al 80% del objetivo trimestral"
                ),
            }
    return {"valida": True, "mensaje": "Propuesta válida desde la perspectiva de ventas"}


def _impacto_caja(p: Dict[str, Any], caja_actual: float) -> float:
    """finanzas.ts · calcularImpactoCaja."""
    d = p.get("datos_clave") or {}
    impacto = 0.0
    if d.get("ingreso_estimado"):
        impacto += float(d["ingreso_estimado"])
    if d.get("egreso_estimado"):
        impacto -= float(d["egreso_estimado"])
    return caja_actual + impacto


def _impacto_ventas(p: Dict[str, Any]) -> float:
    """ventas.ts · calcularImpactoVentas."""
    d = p.get("datos_clave") or {}
    ventas_actuales = _num(d, "ventas_actuales") or 0.0
    crecimiento = _num(d, "crecimiento_ventas") or 0.0
    return ventas_actuales * (1 + crecimiento / 100)


def _cruzar_datos(
    propuesta: Dict[str, Any], otras: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """ceo.ts · cruzarDatos (ventas↔finanzas, compras↔logistica, finanzas↔ventas)."""
    agente = propuesta.get("agente")
    datos = propuesta.get("datos_clave") or {}

    def _buscar(nombre_agente: str) -> Optional[Dict[str, Any]]:
        for otra in otras or []:
            if otra.get("agente") == nombre_agente:
                return otra
        return None

    if agente == "ventas":
        fin = _buscar("finanzas")
        margen = _num(datos, "margen_bruto")
        if fin is not None and margen is not None:
            margen_finanzas = _num(fin.get("datos_clave") or {}, "margen_bruto_requerido")
            if margen_finanzas is not None and margen < margen_finanzas:
                return {
                    "conflicto": True,
                    "mensaje": (
                        f"Ventas propone margen {margen:g}% pero Finanzas "
                        f"requiere {margen_finanzas:g}%"
                    ),
                }
    elif agente == "compras":
        log = _buscar("logistica")
        stock = _num(datos, "stock_solicitado")
        if log is not None and stock is not None:
            capacidad = _num(log.get("datos_clave") or {}, "capacidad_maxima")
            if capacidad is not None and stock > capacidad:
                return {
                    "conflicto": True,
                    "mensaje": (
                        f"Compras solicita stock {stock:g} pero Logística solo "
                        f"puede manejar {capacidad:g}"
                    ),
                }
    elif agente == "finanzas":
        ven = _buscar("ventas")
        caja = _num(datos, "caja_proyectada")
        if ven is not None and caja is not None:
            impacto_ventas = _impacto_ventas(ven)
            if caja < impacto_ventas:
                return {
                    "conflicto": True,
                    "mensaje": (
                        f"Finanzas proyecta caja ${caja:g} pero Ventas requiere "
                        f"${impacto_ventas:g}"
                    ),
                }
    return {"conflicto": False, "mensaje": "Sin conflictos detectados"}


def _requiere_escalamiento(p: Dict[str, Any]) -> bool:
    """ceo.ts · requiereEscalamiento (monto > umbral o riesgo legal alto)."""
    datos = p.get("datos_clave") or {}
    monto = _num(datos, "monto")
    if monto is not None and monto > CONTEXTO_EUREKA["umbral_escalamiento"]["monto"]:
        return True
    if p.get("riesgo") == "alto" and datos.get("riesgo_legal"):
        return True
    return False


# ── ventas-observador (ventas-observador.ts) ─────────────────────────────────
def _evaluar_observaciones_ventas(p: Dict[str, Any]) -> Dict[str, Any]:
    import time

    d = p.get("datos_clave") or {}
    obj = CONTEXTO_EUREKA["objetivo_trimestral"]
    res: Dict[str, Any] = {
        "agente": "ventas-observador",
        "propuestaId": d.get("propuestaId") or f"prop-{int(time.time() * 1000)}",
        "evaluacion": "",
        "riesgos": [],
        "conflictosCon": [],
        "mejorasPropuestas": [],
        "tradeOff": "",
        "severidad": "sugerencia",
        "recomendacionAlCeo": "aprobar",
    }
    riesgos: List[str] = res["riesgos"]
    conflictos: List[str] = res["conflictosCon"]
    mejoras: List[str] = res["mejorasPropuestas"]

    margen = _num(d, "margen_bruto")
    crecimiento = _num(d, "crecimiento_ventas")

    # 1. Alineación con objetivos trimestrales
    if margen is not None:
        if margen < obj["margen_bruto"]:
            riesgos.append(
                f"Margen bruto {d.get('margen_bruto')}% por debajo del objetivo "
                f"trimestral ({obj['margen_bruto']}%)"
            )
            conflictos.append("finanzas")
            res["severidad"] = "advertencia"
        else:
            res["evaluacion"] += "Margen bruto alineado con objetivos trimestrales. "
    if crecimiento is not None:
        if crecimiento < obj["crecimiento_ventas"]:
            riesgos.append(
                f"Crecimiento de ventas {d.get('crecimiento_ventas')}% por debajo "
                f"del objetivo trimestral ({obj['crecimiento_ventas']}%)"
            )
            res["severidad"] = "advertencia"
        else:
            res["evaluacion"] += (
                "Crecimiento de ventas alineado con objetivos trimestrales. "
            )

    # 2. Riesgo de venta bajo costo
    if margen is not None and margen <= 0:
        riesgos.append("Venta bajo costo viola valores no negociables de EUREKA")
        conflictos.append("finanzas")
        res["severidad"] = "critica"
        res["recomendacionAlCeo"] = "rechazar"

    # 3. Conflictos con otros agentes (caja)
    caja = _num(d, "caja_proyectada")
    if caja is not None:
        caja_minima = CONTEXTO_EUREKA["restricciones"]["caja_minima"]
        if caja < caja_minima:
            riesgos.append(
                f"Caja proyectada ${d.get('caja_proyectada')} por debajo del "
                f"mínimo (${caja_minima})"
            )
            conflictos.append("finanzas")
            res["severidad"] = "critica"
            res["recomendacionAlCeo"] = "solicitar_ajustes"

    # 4. Mejoras concretas
    if margen is not None and margen < obj["margen_bruto"]:
        mejoras.append(
            f"Aumentar margen bruto en {obj['margen_bruto'] - margen:.1f}% mediante "
            f"optimización de costos o ajuste de precios"
        )
    if crecimiento is not None and crecimiento < obj["crecimiento_ventas"]:
        mejoras.append(
            f"Implementar estrategia de crecimiento para aumentar ventas en "
            f"{obj['crecimiento_ventas'] - crecimiento:.1f}%"
        )
    if not mejoras:
        mejoras.append(
            "Realizar análisis de mercado para identificar oportunidades de optimización"
        )

    # 5. Trade-off explícito
    if margen is not None and crecimiento is not None:
        if margen > obj["margen_bruto"] and crecimiento < obj["crecimiento_ventas"]:
            res["tradeOff"] = (
                "Alto margen vs bajo crecimiento: priorizar margen a corto plazo "
                "puede limitar expansión de mercado"
            )
        elif margen < obj["margen_bruto"] and crecimiento > obj["crecimiento_ventas"]:
            res["tradeOff"] = (
                "Bajo margen vs alto crecimiento: crecimiento acelerado puede "
                "comprometer rentabilidad"
            )
        else:
            res["tradeOff"] = (
                "Equilibrio entre margen y crecimiento alineado con objetivos estratégicos"
            )
    else:
        res["tradeOff"] = (
            "Enfoque en mantener equilibrio entre objetivos comerciales y "
            "restricciones financieras"
        )

    # 6. Severidad final
    if any("viola valores no negociables" in r for r in riesgos):
        res["severidad"] = "critica"
        res["recomendacionAlCeo"] = "rechazar"
    elif riesgos:
        res["severidad"] = "advertencia"
        if res["recomendacionAlCeo"] == "aprobar":
            res["recomendacionAlCeo"] = "solicitar_ajustes"

    # 7. Evaluación completa
    if not res["evaluacion"]:
        res["evaluacion"] = (
            "Propuesta evaluada desde perspectiva comercial con observaciones adjuntas."
        )
    return res


# ── CEO (src/core/ceo.ts · _tomarDecision) ───────────────────────────────────
def tomar_decision(
    propuesta: Dict[str, Any],
    otras_propuestas: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Aplica las 6 reglas de decidirCEO en el mismo orden que el original TS y
    devuelve el MISMO formato que scripts/e2e.js imprime con --json.
    """
    otras = otras_propuestas or []
    agente = str(propuesta.get("agente", ""))
    datos = propuesta.get("datos_clave") or {}

    validaciones = {
        "finanzas": _validar_finanzas(propuesta),
        "logistica": _validar_logistica(propuesta),
        "compras": _validar_compras(propuesta),
        "ventas": _validar_ventas(propuesta),
    }
    observacion = _evaluar_observaciones_ventas(propuesta)
    validacion_origen = validaciones.get(agente) or validaciones["ventas"]

    aportes_agentes = dict(validaciones)
    aportes_agentes["ventas-observador"] = observacion

    cruce = _cruzar_datos(propuesta, otras)

    decision: Dict[str, Any] = {
        "decision": "aprobado",
        "justificacion": "",
        "agentes_notificados": [agente],
        "siguiente_paso": "Implementar propuesta",
        "aportes_agentes": aportes_agentes,
        "run_id": None,
    }
    if agente == "ventas" and observacion:
        decision["agentes_notificados"].append("ventas-observador")

    # Regla 1 · Priorizar caja disponible
    caja_proyectada = _num(datos, "caja_proyectada")
    if caja_proyectada is not None:
        caja_actual = _num(datos, "caja_actual") or 100_000_000.0
        impacto = _impacto_caja(propuesta, caja_actual)
        caja_minima = CONTEXTO_EUREKA["restricciones"]["caja_minima"]
        if impacto < caja_minima:
            decision["decision"] = "rechazado"
            decision["justificacion"] = (
                f"caja proyectada ${impacto:g} cae bajo el mínimo de "
                f"${caja_minima}. Priorizando liquidez sobre crecimiento."
            )
            decision["siguiente_paso"] = "Buscar alternativa con menor impacto en caja"
            return decision

    # Regla 2 · Validación del agente origen
    if not validacion_origen["valida"]:
        decision["decision"] = "rechazado"
        decision["justificacion"] = (
            f"Propuesta inválida: {validacion_origen['mensaje']}"
        )
        decision["siguiente_paso"] = "Reformular propuesta"
        return decision

    # Regla 3 · Escalamiento
    if _requiere_escalamiento(propuesta):
        decision["decision"] = "escalado_a_humano"
        decision["justificacion"] = (
            "Propuesta supera umbral de escalamiento: monto o riesgo legal"
        )
        decision["siguiente_paso"] = "Revisión por humano"
        return decision

    # Regla 4 · Conflictos cruzados
    if cruce["conflicto"]:
        decision["decision"] = "reformular"
        decision["justificacion"] = f"Conflicto detectado: {cruce['mensaje']}"
        decision["condiciones"] = ["Resolver conflicto con el agente afectado"]
        decision["siguiente_paso"] = "Negociación entre agentes"
        return decision

    # REGLA 5 · Veto cruzado (ninguna objeción se ignora)
    objeciones = [
        f"{nombre}: {res['mensaje']}"
        for nombre, res in validaciones.items()
        if not res["valida"]
    ]
    observador_critico = bool(observacion) and (
        observacion.get("severidad") == "critica"
        or observacion.get("recomendacionAlCeo") == "rechazar"
    )
    if objeciones or observador_critico:
        detalle = list(objeciones)
        if observador_critico:
            detalle.append(
                f"ventas-observador ({observacion.get('severidad')}/"
                f"{observacion.get('recomendacionAlCeo')}): "
                f"{str(observacion.get('evaluacion', '')).strip()}"
            )
        decision["decision"] = "escalado_a_humano"
        decision["justificacion"] = (
            "Aprobación automática bloqueada por objeciones entre agentes. "
            + " | ".join(detalle)
        )
        decision["condiciones"] = detalle
        decision["siguiente_paso"] = (
            "Revisión humana: arbitrar las objeciones y re-someter"
        )
        return decision

    # REGLA 6 · La recomendación del observador nunca se ignora
    recomendacion = (observacion or {}).get("recomendacionAlCeo", "aprobar")
    if recomendacion != "aprobar":
        if recomendacion == "escalar":
            decision["decision"] = "escalado_a_humano"
            decision["justificacion"] = (
                f"El ventas-observador recomienda escalar: "
                f"{str(observacion.get('evaluacion', '')).strip()}"
            )
            decision["siguiente_paso"] = "Revisión humana"
            return decision
        if recomendacion == "solicitar_ajustes":
            decision["decision"] = "reformular"
            decision["justificacion"] = (
                "El ventas-observador solicita ajustes antes de aprobar: "
                + " ".join(observacion.get("mejorasPropuestas") or [])
            )
            decision["condiciones"] = list(observacion.get("mejorasPropuestas") or [])
            decision["siguiente_paso"] = (
                "Incorporar las mejoras propuestas y re-someter"
            )
            return decision

    # Aprobado · los 5 aportes son favorables
    decision["justificacion"] = (
        f"Propuesta validada por los 5 agentes sin objeciones. "
        f"{validacion_origen['mensaje']}. {cruce['mensaje']}."
    )
    return decision


def tomar_decision_json(propuesta: Dict[str, Any]) -> Dict[str, Any]:
    """Formato idéntico al payload --json de scripts/e2e.js."""
    resultado = tomar_decision(propuesta)
    return {
        "decision": resultado["decision"],
        "justificacion": resultado["justificacion"],
        "trade_off": (resultado.get("aportes_agentes", {}).get("ventas-observador") or {}).get(
            "tradeOff", ""
        ),
        "run_id": None,
        "langsmith_url": None,
        "aportes_agentes": resultado["aportes_agentes"],
        "aportes_gemini": None,
    }


if __name__ == "__main__":  # pragma: no cover - utilidad manual
    import json
    import sys

    if len(sys.argv) < 2:
        print('Uso: python src/agents/ceo_python.py \'{"agente":"ventas",...}\'')
        raise SystemExit(2)
    print(json.dumps(tomar_decision_json(json.loads(sys.argv[1])), ensure_ascii=False))







