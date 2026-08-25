#!/usr/bin/env python3
"""
EUREKA · Agente de PROPUESTAS COMERCIALES (línea de venta hacia clientes).

Segundo agente de la línea. Recibe el dossier JSON producido por
marketing-prospeccion.py, lo cruza con el catálogo de servicios
(config/catalogo-servicios.json) y redacta una propuesta comercial.

GARANTÍAS:
  · La selección de tier es DETERMINÍSTICA (código, no LLM): jamás inventa
    un tier ni un precio fuera del catálogo.
  · Gemini SOLO redacta el texto natural a partir de un brief cerrado con
    los valores literales del catálogo.
  · Antes de considerarse lista, la propuesta pasa por decidirCEO()
    (flujo existente scripts/e2e.js --json, tipo "ventas"): Finanzas veta
    márgenes bajo el objetivo de company.ts (veto cruzado Regla 5).
  · Dossier de confianza baja o con pocas señales ⇒ propuesta genérica que
    propone llamada de diagnóstico primero (requiere_llamada_diagnostico).

Uso:
    python src/agents/propuestas-comerciales.py dossier.json [--margen 30]

Import programático (guion en el nombre ⇒ carga por ruta):
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "propuestas_comerciales",
        pathlib.Path("src/agents/propuestas-comerciales.py"))
    pc = importlib.util.module_from_spec(spec); spec.loader.exec_module(pc)
    pc.crear_propuesta(dossier)

Trazabilidad LangSmith: raíz 'propuestas_comerciales' + spans
'.seleccion_tier' (determinístico), '.redactar' (Gemini texto) y
'.validacion_ceo' (subproceso Node → árbol decidirCEO existente).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

load_dotenv()  # GOOGLE_API_KEY / LANGCHAIN_* antes de crear clientes

from langsmith import traceable  # noqa: E402
from google import genai         # noqa: E402
from google.genai import types   # noqa: E402

MODELO = os.getenv("MARKETING_MODELO", "gemini-3.6-flash")
RUTA_CATALOGO = RAIZ_PROYECTO / "config" / "catalogo-servicios.json"
SCRIPT_E2E = RAIZ_PROYECTO / "scripts" / "e2e.js"

# Margen bruto por defecto atribuido a la propuesta interna cuando el
# comercial no indica uno (por encima del objetivo 25% de company.ts).
MARGEN_BRUTO_DEFECTO = 30.0
E2E_TIMEOUT_S = 300

NO_ENCONTRADO = "no encontrado"
MIN_SENALES_PARA_PRECIO = 2


def _cliente(api_key: Optional[str] = None) -> genai.Client:
    """Cliente Gemini (SDK nuevo); misma GOOGLE_API_KEY que el resto del repo."""
    clave = api_key or os.getenv("GOOGLE_API_KEY")
    if not clave:
        raise ValueError(
            "Google API key requerida: define GOOGLE_API_KEY en .env "
            "(igual que managed_deep_agent_direct.py)."
        )
    return genai.Client(api_key=clave)


def _texto_seguro(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) and valor.strip() else NO_ENCONTRADO


@traceable(name="propuestas-comerciales.catalogo", run_type="tool")
def cargar_catalogo(ruta: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Lee config/catalogo-servicios.json validando su estructura mínima."""
    ruta_archivo = Path(ruta) if ruta else RUTA_CATALOGO
    with open(ruta_archivo, "r", encoding="utf-8") as fh:
        datos = json.load(fh)
    if not isinstance(datos, list) or not datos:
        raise ValueError(f"Catálogo vacío o malformado: {ruta_archivo}")
    for entrada in datos:
        if "tier" not in entrada or "nombre" not in entrada:
            raise ValueError(f"Entrada de catálogo sin tier/nombre: {entrada}")
    return datos


def _entrada_tier(
    catalogo: List[Dict[str, Any]], tier: int
) -> Optional[Dict[str, Any]]:
    for entrada in catalogo:
        if int(entrada.get("tier", -1)) == tier:
            return entrada
    return None


def _rango_precio(entrada: Dict[str, Any]) -> List[int]:
    """Normaliza precio_clp=[min,max] o precio_clp_desde=X a [min,max]."""
    if "precio_clp" in entrada:
        rango = entrada["precio_clp"]
        return [int(rango[0]), int(rango[-1])]
    if "precio_clp_desde" in entrada:
        desde = int(entrada["precio_clp_desde"])
        return [desde, desde]
    raise ValueError(f"Entrada sin precio definido: {entrada.get('nombre')}")


def _tiempo(entrada: Dict[str, Any]) -> List[int]:
    t = entrada.get("tiempo_semanas") or [0, 0]
    return [int(t[0]), int(t[-1])]


_KW_T1 = ("chatbot", "atención", "atencion", "soporte", "faq", "web", "contenido")
_KW_T2 = ("multiagente", "agente", "datos", "automatizaci", "proceso", "analític", "analitic", "generativa", "llm")
_KW_T3 = ("integraci", "erp", "crm", "cloud", "infraestructura", "ciberseguridad", "migraci", "legacy", "enterprise", "escalabilidad")


@traceable(name="propuestas-comerciales.seleccion_tier", run_type="tool")
def seleccionar_tier(
    dossier: Dict[str, Any], catalogo: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Selección DETERMINÍSTICA del tier (código, nunca el LLM).

    Reglas: tamaño 'grande' parte en tier 2, resto en tier 1; las palabras
    clave de las señales pueden SUMAR tiers superiores (combinación). Con
    confianza baja o pocas señales se marca llamada de diagnóstico.
    """
    senales = [
        s for s in (dossier.get("senales_de_necesidad") or []) if isinstance(s, str)
    ]
    texto = " ".join(senales).lower()
    confianza = str(dossier.get("confianza", "")).lower()
    tamano = str(dossier.get("tamano_estimado", "")).lower()

    puntaje = {
        1: sum(k in texto for k in _KW_T1),
        2: sum(k in texto for k in _KW_T2),
        3: sum(k in texto for k in _KW_T3),
    }

    base = 2 if tamano == "grande" else 1
    tiers_seleccionados = {base}
    for tier_num in (1, 2, 3):
        if puntaje[tier_num] > 0:
            tiers_seleccionados.add(tier_num)

    requiere_diag = confianza == "baja" or len(senales) < MIN_SENALES_PARA_PRECIO

    entradas = sorted(
        (
            e
            for e in (_entrada_tier(catalogo, t) for t in tiers_seleccionados)
            if e is not None
        ),
        key=lambda e: int(e["tier"]),
    )
    precios = [_rango_precio(e) for e in entradas]
    tiempos = [_tiempo(e) for e in entradas]
    rango_precio = [min(p[0] for p in precios), max(p[1] for p in precios)]
    rango_tiempo = [min(t[0] for t in tiempos), max(t[1] for t in tiempos)]

    nombres = " + ".join(str(e["nombre"]) for e in entradas)
    combinado = len(entradas) > 1
    justificacion = (
        f"Tamaño '{dossier.get('tamano_estimado', NO_ENCONTRADO)}' ⇒ base tier "
        f"{base}; señales detectadas ({len(senales)}) activan "
        f"{'combinación' if combinado else 'el tier'}: {nombres}."
    )
    if requiere_diag:
        justificacion += (
            " Confianza baja o señales insuficientes ⇒ se propone primero una "
            "llamada de diagnóstico en lugar de un precio cerrado."
        )

    return {
        "tier_principal": int(max(tiers_seleccionados)),
        "tiers": sorted(tiers_seleccionados),
        "nombres": nombres,
        "entradas": entradas,
        "justificacion_tier": justificacion,
        "rango_precio_clp": rango_precio,
        "tiempo_estimado_semanas": rango_tiempo,
        "requiere_llamada_diagnostico": requiere_diag,
    }


def _construir_propuesta_interna(
    dossier: Dict[str, Any],
    seleccion: Dict[str, Any],
    margen_bruto_estimado: float,
) -> Dict[str, Any]:
    """
    Traduce la propuesta comercial a una propuesta interna tipo 'ventas'
    para que decidirCEO() la valide con sus reglas reales (margen objetivo
    y caja mínima ya configurados en company.ts, vía los agentes TS).
    """
    empresa = dossier.get("empresa", "prospecto")
    return {
        "agente": "ventas",
        "tipo": "propuesta",
        "resumen": (
            f"Propuesta comercial tier {seleccion['tier_principal']} "
            f"({seleccion['nombres']}) para {empresa}"
        ),
        "datos_clave": {
            "margen_bruto": margen_bruto_estimado,
            "monto": seleccion["rango_precio_clp"][1],
            "tier": seleccion["tier_principal"],
            "precio_clp": seleccion["rango_precio_clp"],
            "tiempo_semanas": seleccion["tiempo_estimado_semanas"],
            "empresa_prospecto": empresa,
        },
        "riesgo": "medio",
        "requiere_aprobacion_ceo": True,
    }


@traceable(name="propuestas-comerciales.validacion_ceo", run_type="tool")
def validar_con_decidir_ceo(
    propuesta_interna: Dict[str, Any],
) -> Dict[str, Any]:
    """
    FASE DE VALIDACIÓN · Reutiliza el flujo existente scripts/e2e.js --json
    (mismo patrón que app_streamlit.py): la propuesta interna viaja por la
    variable de entorno EUREKA_PROPUESTA_JSON y decidirCEO() aplica sus
    reglas reales (caja mínima, margen objetivo, veto cruzado de agentes).
    """
    env = os.environ.copy()
    env["EUREKA_PROPUESTA_JSON"] = json.dumps(
        propuesta_interna, ensure_ascii=False
    )
    proc = subprocess.run(
        ["node", str(SCRIPT_E2E), "--json"],
        cwd=str(RAIZ_PROYECTO),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=E2E_TIMEOUT_S,
    )

    salida = (proc.stdout or "").strip()
    inicio = salida.find("{")
    payload: Optional[Dict[str, Any]] = None
    if inicio != -1:
        try:
            cargado = json.loads(salida[inicio:])
            if isinstance(cargado, dict):
                payload = cargado
        except json.JSONDecodeError:
            payload = None
    if payload is None:
        detalle = ((proc.stderr or "").strip()[-800:]) or "(sin stderr)"
        raise RuntimeError(
            f"e2e.js terminó con código {proc.returncode} sin JSON.\n{detalle}"
        )

    decision = str(payload.get("decision", "")).lower()
    return {
        "decision": decision,
        "lista_para_enviar": decision == "aprobado",
        "detalle": str(payload.get("justificacion", ""))[:400],
        "run_id": payload.get("run_id"),
        "langsmith_url": payload.get("langsmith_url"),
        # Aportes individuales de los 5 agentes (para vistas tipo tarjetas):
        "aportes_agentes": payload.get("aportes_agentes") or {},
    }


SYSTEM_PROMPT = """Eres el redactor comercial de EUREKA, empresa que desarrolla \
agentes y multiagentes de IA a medida para pymes y grandes empresas.

Recibirás un BRIEF estructurado con: diagnóstico (señales detectadas en el \
prospecto), tier(s) recomendados con su alcance LITERAL del catálogo, rango \
de inversión en CLP, tiempo estimado en semanas, y una marca de si procede \
primero una llamada de diagnóstico.

REGLAS ABSOLUTAS:
1. Usa SOLO la información del brief. PROHIBIDO inventar cifras, tiers, \
plazos, descuentos o capacidades que no estén explícitos en él.
2. Precios y plazos se comunican EXACTAMENTE como figuran en el brief.
3. Si el brief marca llamada_de_diagnostico=true, el texto NO incluye \
cifras: propone una llamada de diagnóstico de 30 minutos como primer paso \
y menciona que la inversión se comparte después, a medida.
4. Tono profesional, cercano y orientado a valor. Español.
5. Estructura: saludo breve → diagnóstico (2-4 frases apoyadas en las \
señales) → solución recomendada (alcance literal del catálogo) → inversión \
y plazos (si aplica) → próximos pasos (2 o 3 pasos concretos y accionables).
6. Responde ÚNICAMENTE con el texto de la propuesta listo para enviar. Sin \
JSON, sin corchetes de sección, sin notas internas para el vendedor.
"""


def _clp(valor: int) -> str:
    """Formatea un entero CLP con puntos de miles (solo presentación)."""
    return f"{valor:,}".replace(",", ".")


def _descripcion_inversion(entrada: Dict[str, Any]) -> str:
    """Texto literal del catálogo para la línea de cada tier del brief."""
    if "precio_clp_desde" in entrada:
        return (
            f"desde $CLP {_clp(int(entrada['precio_clp_desde']))} "
            f"({entrada['tiempo_semanas'][0]}-{entrada['tiempo_semanas'][1]} semanas)"
        )
    rango = entrada["precio_clp"]
    return (
        f"$CLP {_clp(int(rango[0]))} a {_clp(int(rango[1]))} "
        f"({entrada['tiempo_semanas'][0]}-{entrada['tiempo_semanas'][1]} semanas)"
    )


def _construir_prompt(
    dossier: Dict[str, Any], seleccion: Dict[str, Any]
) -> str:
    """Embede el brief cerrado: señales + tiers/precios literales del catálogo."""
    diagnostico = seleccion["requiere_llamada_diagnostico"]
    partes = ["BRIEF PARA REDACTAR LA PROPUESTA", ""]
    partes.append(f"Empresa prospecto: {dossier.get('empresa', 'prospecto')}")
    partes.append(f"Rubro: {_texto_seguro(dossier.get('rubro'))}")
    partes.append("")
    partes.append("DIAGNÓSTICO · señales detectadas:")
    senales = [s for s in (dossier.get("senales_de_necesidad") or []) if isinstance(s, str)]
    for s in senales:
        partes.append(f"  - {s}")
    if not senales:
        partes.append("  - (sin señales específicas; investigación preliminar)")
    partes.append("")
    partes.append(
        "SOLUCIÓN RECOMENDADA (nombres y alcances LITERALES del catálogo):"
    )
    for e in seleccion["entradas"]:
        partes.append(f"  - Tier {e['tier']}: {e['nombre']}")
        partes.append(f"    Alcance: {e.get('alcance', '')}")
        partes.append(f"    Inversión y plazo: {_descripcion_inversion(e)}")
    partes.append("")
    partes.append(f"llamada_de_diagnostico={str(diagnostico).lower()}")
    if diagnostico:
        partes.append(
            "⇒ El texto NO debe contener cifras ni plazos: propone primero una "
            "llamada de diagnóstico de 30 minutos y deja la inversión para después."
        )
    partes.append("")
    partes.append(
        "Redacta ahora la propuesta comercial completa siguiendo las REGLAS."
    )
    return "\n".join(partes)


@traceable(name="propuestas-comerciales.redactar", run_type="tool")
def _redactar_texto_gemini(cliente: genai.Client, prompt: str) -> str:
    """Gemini redacta el texto a partir del brief cerrado (sin tools).
    Reintenta ante 429/503 transitorios del tier gratuito."""
    ultimo_error: Optional[Exception] = None
    respuesta = None
    for intento in range(3):
        try:
            chat = cliente.chats.create(
                model=MODELO,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.4,
                ),
            )
            respuesta = chat.send_message(prompt)
            break
        except Exception as exc:  # noqa: BLE001
            ultimo_error = exc
            mensaje = str(exc)
            reintentable = (
                "429" in mensaje
                or "503" in mensaje
                or "RESOURCE_EXHAUSTED" in mensaje.upper()
                or "UNAVAILABLE" in mensaje.upper()
            )
            if reintentable and intento < 2:
                time.sleep((6, 20)[intento])
                continue
            raise
    if respuesta is None:  # agotó reintentos
        raise ultimo_error  # type: ignore[misc]
    return respuesta.text or ""


_PLANTILLA_DIAGNOSTICO = (
    "Hola {empresa},\n\n"
    "Revisamos públicamente su actividad ({rubro}) y queremos proponerte una "
    "conversación de diagnóstico de 30 minutos: cuéntanos dónde sienten "
    "fricción operativa y te mostramos, con ejemplos concretos, cómo un "
    "agente o multiagente de IA podría ayudarte.\n\n"
    "Después de esa llamada compartimos una propuesta a medida.\n\n"
    "Un saludo,\nEquipo EUREKA"
)


@traceable(name="propuestas_comerciales", run_type="chain")
def crear_propuesta(
    dossier: Dict[str, Any],
    margen_bruto_estimado: float = MARGEN_BRUTO_DEFECTO,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Orquesta: catálogo → selección determinística → validación decidirCEO()
    → redacción Gemini. Nunca lanza hacia arriba: devuelve 'error' si algo
    estructural falla, y la entrega nunca queda sin texto (plantilla base).
    """
    empresa = dossier.get("empresa", "prospecto")

    try:
        catalogo = cargar_catalogo()
        seleccion = seleccionar_tier(dossier, catalogo)
    except Exception as exc:  # noqa: BLE001
        return {"empresa": empresa, "error": f"Catálogo/selección de tier: {exc}"}

    propuesta_interna = _construir_propuesta_interna(
        dossier, seleccion, margen_bruto_estimado
    )
    try:
        validacion = validar_con_decidir_ceo(propuesta_interna)
    except Exception as exc:  # noqa: BLE001
        validacion = {
            "decision": "error",
            "lista_para_enviar": False,
            "detalle": str(exc)[:400],
            "run_id": None,
            "langsmith_url": None,
        }

    fallo_redaccion = None
    try:
        texto = _redactar_texto_gemini(
            _cliente(api_key), _construir_prompt(dossier, seleccion)
        )
    except Exception as exc:  # noqa: BLE001
        texto = ""
        fallo_redaccion = str(exc)[:200]

    if not texto.strip():
        # Red de seguridad determinista: la entrega nunca queda vacía.
        if seleccion["requiere_llamada_diagnostico"]:
            texto = _PLANTILLA_DIAGNOSTICO.format(
                empresa=empresa,
                rubro=_texto_seguro(dossier.get("rubro")),
            )
        else:
            e0 = seleccion["entradas"][0]
            texto = (
                f"Hola {empresa},\n\nPropuesta: {e0['nombre']} — "
                f"{e0.get('alcance', '')}\nInversión: "
                f"{_descripcion_inversion(e0)}.\n\n"
                "Quedamos atentos a tus comentarios.\nEquipo EUREKA"
            )

    return {
        "empresa": empresa,
        "tier_recomendado": seleccion["tier_principal"],
        "justificacion_tier": seleccion["justificacion_tier"],
        "rango_precio_clp": seleccion["rango_precio_clp"],
        "tiempo_estimado_semanas": seleccion["tiempo_estimado_semanas"],
        "propuesta_texto": texto,
        "requiere_llamada_diagnostico": seleccion["requiere_llamada_diagnostico"],
        "fuente_catalogo": "config/catalogo-servicios.json",
        # Integración decidirCEO: estado de aprobación interna antes del envío
        "lista_para_enviar": bool(validacion.get("lista_para_enviar"))
        and fallo_redaccion is None,
        "validacion_ceo": validacion,
        "propuesta_interna_validada": propuesta_interna,
        **({"error_redaccion": fallo_redaccion} if fallo_redaccion else {}),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Agente de Propuestas Comerciales EUREKA"
    )
    parser.add_argument(
        "dossier", help="Ruta al dossier JSON producido por marketing-prospeccion"
    )
    parser.add_argument(
        "--margen",
        type=float,
        default=MARGEN_BRUTO_DEFECTO,
        help="Margen bruto estimado del deal en %% (default 30)",
    )
    args = parser.parse_args()

    with open(args.dossier, "r", encoding="utf-8") as fh:
        dossier = json.load(fh)

    resultado = crear_propuesta(dossier, margen_bruto_estimado=args.margen)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()