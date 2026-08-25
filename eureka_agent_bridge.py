#!/usr/bin/env python3
"""
EUREKA - Puente del agente Gemini para LangSmith (subproceso).

Lee la propuesta (JSON) desde el entorno (EUREKA_PROPUESTA_JSON) y el contexto
de traza del run padre 'decidirCEO' de Node.js (LANGSMITH_DOTTED_ORDER /
LANGSMITH_BAGGAGE). Se une al árbol de traza existente como un span hijo
llamado 'gemini_agent' que a su vez contiene los spans de Gemini:
  gemini_agent
    ├── get_eureka_context            (@traceable ya decorado)
    ├── validate_financial_proposal   (@traceable ya decorado)
    └── run / managed_deep_agent_direct (llamada a Gemini)

Imprime en stdout un JSON con {ok, resultado} como respuesta para Node.
"""
import json
import os
import sys
import traceback
import warnings

from dotenv import load_dotenv

# Cargar el .env ANTES de crear cualquier cliente de LangSmith/Gemini
load_dotenv()

# Silenciar el aviso de deprecación de google.generativeai (no afecta el trazado)
warnings.filterwarnings("ignore", category=FutureWarning)

from langsmith import traceable  # noqa: E402


def _headers_padre() -> dict:
    """Construye el mapping 'langsmith-trace' propagado desde Node."""
    headers = {}
    dotted = os.getenv("LANGSMITH_DOTTED_ORDER", "")
    if dotted:
        headers["langsmith-trace"] = dotted
    baggage = os.getenv("LANGSMITH_BAGGAGE", "")
    if baggage:
        headers["baggage"] = baggage
    return headers


@traceable(name="gemini_agent", run_type="tool")
def evaluar_gemini(propuesta: dict, contexto: str) -> dict:
    """Evalúa la propuesta de EUREKA con el agente Gemini (spans hijos)."""
    from managed_deep_agent_direct import ManagedDeepAgentDirect

    agent = ManagedDeepAgentDirect(
        agent_name=os.getenv("EUREKA_AGENT_NAME", "gemini-eureka"),
        api_key=os.getenv("GOOGLE_API_KEY"),
    )

    # Traducción de los datos EUREKA → entrada del validador financiero
    finanzas_propuesta = {
        "gross_margin": propuesta.get("datos_clave", {}).get("margen_bruto"),
        "cash_impact": propuesta.get("datos_clave", {}).get("caja_proyectada"),
    }
    finanzas_propuesta = {
        k: v for k, v in finanzas_propuesta.items() if v is not None
    }

    # Llama a las funciones @traceable de la clase (spans hijos de gemini_agent)
    contexto_eureka = agent.get_eureka_context()  # span: get_eureka
    validacion = agent.validate_financial_proposal(finanzas_propuesta)  # span
    respuesta = agent.run(
        f"Evalúa esta propuesta de {propuesta.get('agente', 'la empresa')} "
        f"de EUREKA considerando los valores no negociables y restricciones "
        f"de la empresa. Propuesta: {propuesta.get('resumen', '')}. Datos: "
        f"{json.dumps(propuesta.get('datos_clave', {}), ensure_ascii=False)}."
    )  # span de Gemini

    return {
        "agente": "gemini",
        "propuestaId": propuesta.get("datos_clave", {}).get(
            "propuestaId", f"gemini-{abs(hash(json.dumps(propuesta, sort_keys=True))) % 10**7}"
        ),
        "respuesta": respuesta,
        "contexto_utilizado": contexto_eureka[:200],
        "validacion_financiera_gemini": validacion,
        "recomendacion": (
            "rechazar"
            if validacion.get("valid") is False
            else "aprobar"
        ),
    }


def main() -> None:
    try:
        propuesta_json = os.getenv("EUREKA_PROPUESTA_JSON")
        if not propuesta_json:
            raise ValueError("Falta EUREKA_PROPUESTA_JSON en el entorno.")
        propuesta = json.loads(propuesta_json)

        contexto = (
            "EUREKA: sector creación de agentes. Obj: margen bruto >25%, "
            "crecimiento +15% QoQ. Restricciones: caja min $50M, deuda máx "
            "$200M. Umbral de escalamiento $100M, riesgo legal, conflictos "
            "irresolubles. Valores: no vender bajo costo, cumplir plazos legales."
        )

        parent_headers = _headers_padre()
        langsmith_extra = {"parent": parent_headers} if parent_headers else {}

        resultado = evaluar_gemini(propuesta, contexto, langsmith_extra=langsmith_extra)

        print(json.dumps({"ok": True, "resultado": resultado}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        msg = f"{e}\n{traceback.format_exc()}"
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()