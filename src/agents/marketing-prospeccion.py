#!/usr/bin/env python3
"""
EUREKA · Agente de MARKETING / PROSPECCIÓN (nueva línea: ventas hacia clientes).

Primer agente de la línea de venta de agentes/multiagentes de IA a medida
para pymes y grandes empresas. Dado el nombre de una empresa prospecto,
investiga por SU CUENTA con el grounding de Google Search de Gemini y
devuelve un dossier estructurado en JSON.

GARANTÍAS DE HONESTIDAD:
  · NUNCA inventa datos: campo sin evidencia → "no encontrado" (o lista vacía).
  · FUENTES REALES: 'fuentes' son EXCLUSIVAMENTE las URLs devueltas por la
    búsqueda (Tavily); lo que el modelo declare como fuente se IGNORA.
  · Anti-datos-personales: solo negocio; perfiles personales de LinkedIn
    (/in/) descartados por código además de prohibidos en el system prompt.

ARQUITECTURA EN DOS FASES (sin grounding nativo de Gemini):
  Fase 1 · BÚSQUEDA → Tavily trae snippets + URLs reales (plan gratis:
           1.000 créditos/mes SIN tarjeta; ver bloque LÍMITE más abajo).
  Fase 2 · REDACCIÓN → Gemini (uso de TEXTO, gratuito y sin tarjeta)
           recibe esos resultados embebidos en el prompt y redacta el
           dossier SOLO con ellos. Sin tools, sin AFC.
El resto del repo sigue sobre google.generativeai (deprecado); este módulo
usa el SDK nuevo google-genai y no toca el viejo.

Uso CLI:
    python src/agents/marketing-prospeccion.py "Mercadona" [rubro_hint]

Import programático (el guion del nombre obliga a cargarlo por ruta):
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "marketing_prospeccion",
        pathlib.Path("src/agents/marketing-prospeccion.py"))
    mp = importlib.util.module_from_spec(spec); spec.loader.exec_module(mp)
    mp.investigar_empresa("Mercadona")

Trazabilidad LangSmith: run raíz 'marketing_prospeccion' + span hijo
'marketing-prospeccion.buscar'. Aún SIN conectar a decidirCEO (por diseño).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

load_dotenv()  # GOOGLE_API_KEY / LANGCHAIN_* antes de crear clientes

from langsmith import traceable  # noqa: E402
from google import genai         # noqa: E402  ← SDK nuevo
from google.genai import types   # noqa: E402

# Generación vigente que la propia API recomienda para features nuevos como
# el grounding (con 'gemini-2.0-flash' hoy se recibe 404). Sobrescribible
# vía .env sin tocar código.
MODELO = os.getenv("MARKETING_MODELO", "gemini-3.6-flash")

# ─────────────────────────────────────────────────────────────────────────────
# LÍMITE GRATUITO DE LA BÚSQUEDA (TAVILY) — verificado en tavily.com/pricing:
#   · Plan Free: 1.000 créditos/mes, SIN tarjeta de crédito.
#   · Los créditos se resetean el día 1 de cada mes.
#   · Una búsqueda 'basic' consume 1 crédito ⇒ 1 investigación de empresa
#     = 1 crédito ⇒ ~1.000 empresas/mes (~33/día de media).
#   · Clave gratuita en https://app.tavily.com → TAVILY_API_KEY en .env
# ─────────────────────────────────────────────────────────────────────────────
TAVILY_ENDPOINT = "https://api.tavily.com/search"
TAVILY_TIMEOUT_S = 30
MAX_RESULTADOS_BUSQUEDA = 10

NO_ENCONTRADO = "no encontrado"
CONFIANZAS_VALIDAS = ("alta", "media", "baja")
TAMANOS_VALIDOS = ("pyme", "grande")

SYSTEM_PROMPT = """Eres el agente de MARKETING Y PROSPECCIÓN de EUREKA, empresa que \
desarrolla agentes y multiagentes de IA a medida para pymes y grandes empresas.

TU ÚNICO TRABAJO: analizar los RESULTADOS DE BÚSQUEDA WEB que te entrega el \
sistema sobre una empresa prospecto y redactar con ellos un dossier JSON para \
el equipo comercial. No tienes acceso a búsquedas: solo ves ese texto.

POLÍTICA DE INVESTIGACIÓN (ESTRICTA):
1. SOLO información pública de negocio: sitio web corporativo, página de LinkedIn \
de la EMPRESA, noticias/prensa, presencia digital general (redes corporativas, \
directorios B2B).
2. PROHIBIDO recolectar datos personales de empleados individuales: nombres de \
personas, correos, teléfonos, perfiles personales de LinkedIn (/in/), sueldos.
3. DECLARA LA FUENTE: cada dato debe aparecer literalmente en los RESULTADOS \
entregados (en su título, contenido o URL). PROHIBIDO citar URLs que no \
estén en esos resultados o añadir conocimiento propio.
4. NUNCA INVENTES: si un dato no aparece en tus resultados, escribe exactamente \
"no encontrado" (o lista vacía). Prohibido rellenar con suposiciones, \
inferencias no respaldadas o datos de empresas homónimas sin confirmar.

CRITERIO tamano_estimado: "grande" (cientos/miles de empleados públicos, \
multinacional, cotizada); "pyme" (pequeña/mediana según su web o directorios); \
"no encontrado" si no hay evidencia suficiente.

REGLA DE CONFIANZA: "alta" con ≥2 fuentes independientes y datos clave hallados; \
"media" con 1 fuente sólida o datos parciales; "baja" con evidencia escasa.

SALIDA: responde EXCLUSIVAMENTE con UN objeto JSON válido (sin markdown ni \
texto extra), con EXACTAMENTE estas claves:
{"empresa": string,
 "rubro": string,
 "tamano_estimado": "pyme"|"grande"|"no encontrado",
 "presencia_digital": {"sitio_web": string, "linkedin": string},
 "senales_de_necesidad": [string],
 "fuentes": [string],
 "confianza": "alta"|"media"|"baja"}

senales_de_necesidad: indicios PÚBLICOS de que podría necesitar agentes, \
chatbots o automatización con IA (ej.: "sin chatbot visible en su sitio", \
"oferta de empleo buscando perfiles de datos/IA"). Máximo 6, cada una ≤180 \
caracteres, citando fuente entre corchetes cuando aplique ([fuente: dominio]).
Textos libres en español."""


def _cliente(api_key: Optional[str] = None) -> genai.Client:
    """Cliente Gemini (SDK nuevo); misma GOOGLE_API_KEY que el resto del repo."""
    clave = api_key or os.getenv("GOOGLE_API_KEY")
    if not clave:
        raise ValueError(
            "Google API key requerida: define GOOGLE_API_KEY en .env "
            "(igual que managed_deep_agent_direct.py)."
        )
    return genai.Client(api_key=clave)


@traceable(name="marketing-prospeccion.busqueda_web", run_type="tool")
def _buscar_web_tavily(consulta: str) -> Dict[str, Any]:
    """
    FASE 1 · Búsqueda web vía Tavily (API oficial REST, sin SDK extra).

    Devuelve {'consulta': ..., 'resultados': [{'titulo','url','snippet'}]}.
    Ver bloque 'LÍMITE GRATUITO DE LA BÚSQUEDA (TAVILY)' más arriba:
    1 investigación = 1 crédito del plan Free de 1.000/mes (sin tarjeta).
    """
    clave = os.getenv("TAVILY_API_KEY")
    if not clave:
        raise ValueError(
            "Falta TAVILY_API_KEY en .env. Consíguela gratis y SIN tarjeta "
            "en https://app.tavily.com (plan Free: 1.000 créditos/mes)."
        )

    cuerpo = json.dumps(
        {
            "query": consulta,
            "search_depth": "basic",
            "max_results": MAX_RESULTADOS_BUSQUEDA,
            "include_answer": False,
        }
    ).encode("utf-8")
    peticion = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=cuerpo,
        headers={
            "Authorization": f"Bearer {clave}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(peticion, timeout=TAVILY_TIMEOUT_S) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))

    resultados = []
    for r in datos.get("results", []):
        url = (r.get("url") or "").strip()
        if url.lower().startswith(("http://", "https://")):
            resultados.append(
                {
                    "titulo": (r.get("title") or "").strip(),
                    "url": url,
                    "snippet": (r.get("content") or "").strip()[:800],
                }
            )
    return {"consulta": consulta, "resultados": resultados[:MAX_RESULTADOS_BUSQUEDA]}


@traceable(name="marketing-prospeccion.redactar", run_type="tool")
def _redactar_dossier_gemini(cliente: genai.Client, prompt: str) -> str:
    """
    FASE 2 · Gemini redacta el dossier como uso de TEXTO puro (gratis y sin
    tarjeta): SIN herramienta de grounding ni AFC — el contexto de búsqueda
    ya viene embebido en el prompt por _construir_prompt(). Reintenta ante
    429 transitorio del tier gratuito.
    """
    ultimo_error: Optional[Exception] = None
    respuesta = None
    for intento in range(3):
        try:
            respuesta = cliente.models.generate_content(
                model=MODELO,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                ),
            )
            break
        except Exception as exc:  # noqa: BLE001
            ultimo_error = exc
            mensaje = str(exc)
            # Reintentable: cuota (429) y sobrecarga transitoria del modelo (503)
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
    if respuesta is None:  # agotó reintentos por cuota
        raise ultimo_error  # type: ignore[misc]
    return respuesta.text or ""


def _extraer_json(texto: str) -> Optional[Dict[str, Any]]:
    """Extrae el primer bloque JSON balanceado {...} de la respuesta."""
    inicio = texto.find("{")
    while inicio != -1:
        profundidad = 0
        for i in range(inicio, len(texto)):
            if texto[i] == "{":
                profundidad += 1
            elif texto[i] == "}":
                profundidad -= 1
                if profundidad == 0:
                    try:
                        cargado = json.loads(texto[inicio : i + 1])
                        if isinstance(cargado, dict):
                            return cargado
                    except json.JSONDecodeError:
                        break
        inicio = texto.find("{", inicio + 1)
    return None


def _texto_seguro(valor: Any) -> str:
    """str no vacío tal cual; cualquier otra cosa → 'no encontrado'."""
    if isinstance(valor, str) and valor.strip():
        return valor.strip()
    return NO_ENCONTRADO


def _url_http(valor: Any) -> str:
    url = _texto_seguro(valor)
    if url != NO_ENCONTRADO and not url.lower().startswith(("http://", "https://")):
        return NO_ENCONTRADO
    return url


def _linkedin_corporativo(valor: Any) -> str:
    """Solo páginas de EMPRESA; perfiles personales (/in/) → no encontrado."""
    url = _texto_seguro(valor)
    if url == NO_ENCONTRADO:
        return url
    bajo = url.lower()
    if "linkedin.com" not in bajo or "/in/" in bajo:
        return NO_ENCONTRADO
    return url


def _limpiar_urls(urls: Any) -> List[str]:
    """
    Solo http(s), sin duplicados, conserva el orden de llegada.
    Además descarta perfiles PERSONALES de LinkedIn (/in/) presentes entre
    los resultados de búsqueda, aplicando la política anti-datos-personales
    también a la lista de 'fuentes' (no solo al campo presencia_digital).
    """
    vistas, limpias = set(), []
    for u in urls or []:
        if isinstance(u, str):
            u = u.strip()
            bajo = u.lower()
            if not bajo.startswith(("http://", "https://")):
                continue
            if "linkedin.com" in bajo and "/in/" in bajo:
                continue
            if u not in vistas:
                vistas.add(u)
                limpias.append(u)
    return limpias


def _normalizar_dossier(
    datos: Dict[str, Any], nombre_empresa: str, urls_busqueda: List[str]
) -> Dict[str, Any]:
    """
    Fuerza el esquema EXACTO de salida y aplica las garantías anti-invento:
    campos vacíos/inválidos → "no encontrado", LinkedIn personal fuera,
    'fuentes' = SOLO URLs devueltas por la búsqueda, confianza acotada.
    """
    presencia_entrada = datos.get("presencia_digital")
    presencia_entrada = presencia_entrada if isinstance(presencia_entrada, dict) else {}

    tamano = _texto_seguro(datos.get("tamano_estimado")).lower()
    if tamano not in TAMANOS_VALIDOS:
        tamano = NO_ENCONTRADO

    senales = [
        s.strip()[:180]
        for s in (datos.get("senales_de_necesidad") or [])
        if isinstance(s, str) and s.strip()
    ][:6]

    # ANTI-ALUCINACIÓN: 'fuentes' = SOLO las URLs reales devueltas por la
    # búsqueda; cualquier fuente que declare el modelo se IGNORA por completo.
    fuentes = _limpiar_urls(urls_busqueda)

    confianza = str(datos.get("confianza", "")).strip().lower()
    if confianza not in CONFIANZAS_VALIDAS or not fuentes:
        confianza = "baja"

    return {
        "empresa": nombre_empresa,
        "rubro": _texto_seguro(datos.get("rubro")),
        "tamano_estimado": tamano,
        "presencia_digital": {
            "sitio_web": _url_http(presencia_entrada.get("sitio_web")),
            "linkedin": _linkedin_corporativo(presencia_entrada.get("linkedin")),
        },
        "senales_de_necesidad": senales,
        "fuentes": fuentes,
        "confianza": confianza,
    }


def _construir_prompt(
    nombre_empresa: str, rubro_hint: Optional[str], busqueda: Dict[str, Any]
) -> str:
    """Embede los resultados de Tavily como ÚNICA fuente permitida del modelo."""
    partes = [f'EMPRESA PROSPECTO: "{nombre_empresa}"']
    if rubro_hint:
        partes.append(f"Sector aproximado declarado por el comercial: {rubro_hint}")
    partes.append("")
    partes.append("RESULTADOS DE BÚSQUEDA WEB (tu ÚNICA fuente de información):")
    resultados = busqueda.get("resultados", [])
    if not resultados:
        partes.append("(la búsqueda no devolvió ningún resultado)")
    for i, r in enumerate(resultados, 1):
        partes.append(f"[{i}] {r['titulo']}")
        partes.append(f"    URL: {r['url']}")
        partes.append(f"    Contenido: {r['snippet']}")
    partes.append("")
    partes.append(
        "Con EXCLUSIVAMENTE esta información redacta el dossier JSON según el "
        'formato definido. Nada fuera de estos resultados puede aparecer; lo '
        'que no esté aquí es "no encontrado". Textos libres en español.'
    )
    return "\n".join(partes)


@traceable(name="marketing_prospeccion", run_type="tool")
def investigar_empresa(
    nombre_empresa: str,
    rubro_hint: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Investiga una empresa prospecto y devuelve su dossier JSON.

    Flujo: Tavily busca snippets+URLs reales → Gemini redacta SOLO con ese
    contexto. En caso de fallo devuelve un dict con la clave "error"
    (+ diagnóstico accionable), nunca un dossier inventado.
    """
    # Consulta orientada a que el sitio OFICIAL aparezca en los primeros
    # resultados (la marca entre comillas evita ruido de homónimos).
    consulta = f'"{nombre_empresa}" sitio web oficial de la empresa'
    if rubro_hint:
        consulta += f" rubro {rubro_hint}"
    consulta += " linkedin"

    # FASE 1 · búsqueda real
    try:
        busqueda = _buscar_web_tavily(consulta)
    except ValueError as exc:  # falta TAVILY_API_KEY → mensaje accionable
        return {"empresa": nombre_empresa, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — red / error HTTP de la API
        return {
            "empresa": nombre_empresa,
            "error": f"Fallo en la búsqueda Tavily: {exc}",
        }

    urls_busqueda = [r["url"] for r in busqueda["resultados"]]

    # FASE 2 · redacción con contexto acotado
    prompt = _construir_prompt(nombre_empresa, rubro_hint, busqueda)
    try:
        texto = _redactar_dossier_gemini(_cliente(api_key), prompt)
    except Exception as exc:  # noqa: BLE001
        return {
            "empresa": nombre_empresa,
            "error": f"Fallo llamando a Gemini: {exc}",
            "fuentes_disponibles": urls_busqueda,
        }

    datos = _extraer_json(texto)
    if datos is None:
        return {
            "empresa": nombre_empresa,
            "error": "Gemini no devolvió JSON parseable",
            "salida_modelo": texto[:600],
            "fuentes_disponibles": urls_busqueda,
        }

    return _normalizar_dossier(datos, nombre_empresa, urls_busqueda)


def main() -> None:
    # CLI en Windows: salida UTF-8 estable aunque se canalice (JSON con acentos)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print('Uso: python src/agents/marketing-prospeccion.py "<empresa>" [rubro]')
        sys.exit(2)
    dossier = investigar_empresa(
        sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None
    )
    print(json.dumps(dossier, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()