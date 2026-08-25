#!/usr/bin/env python3
"""
EUREKA · Agente de SEGUIMIENTO COMERCIAL (línea de venta hacia clientes).

Tercer agente de la línea. Recibe la propuesta generada por
propuestas-comerciales.py más la respuesta/objección del cliente (texto
libre) y decide cómo reaccionar.

REGLAS DUROS (en código, no en prompts):
  · PISOS DE TIER: jamás se ofrece un precio por debajo del mínimo del tier
    ni un plazo por debajo de sus semanas mínimas. Si el pedido queda bajo
    el piso, se baja un tier (si existe y calza) o se contraoferta el piso.
  · LÍMITE DE RONDAS: al llegar a la ronda 3 sin acuerdo (o cualquier ronda
    posterior) el agente NO sigue negociando: devuelve
    requiere_intervencion_humana=True con el resumen de la negociación.
  · OBJECIÓN FUERA DE CATÁLOGO (tipo 'otra'): intervención humana
    inmediata, sin intentar compromisos ni llamar a decidirCEO.

REUTILIZACIÓN: importa propuestas-comerciales.py (catálogo, construcción de
propuesta interna y validación decidirCEO) — cero lógica duplicada.

Salida JSON: {empresa, ronda, tipo_objecion, ajuste_propuesto|null,
validacion_ceo|null, requiere_intervencion_humana, respuesta_texto,
historial_ronda} + referencia_propuesta_origen (run_id/URL del CEO de la
propuesta que origina la negociación, para trazabilidad en LangSmith).

Uso:
    python src/agents/seguimiento-comercial.py propuesta.json "texto objeción" --ronda 2
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

load_dotenv()

from langsmith import traceable  # noqa: E402
from google import genai         # noqa: E402
from google.genai import types   # noqa: E402

# ── Reutilización del agente de propuestas (catálogo + decidirCEO) ──────────
_spec_pc = importlib.util.spec_from_file_location(
    "propuestas_comerciales",
    RAIZ_PROYECTO / "src" / "agents" / "propuestas-comerciales.py",
)
pc = importlib.util.module_from_spec(_spec_pc)
sys.modules["propuestas_comerciales"] = pc
_spec_pc.loader.exec_module(pc)

MODELO = os.getenv("MARKETING_MODELO", "gemini-3.6-flash")

RONDAS_MAXIMAS = 3          # límite DURO de rondas de ajuste
TIPOS_TERMINALES = ("aceptacion", "rechazo_definitivo")

_KW_ACEPTACION = (
    "acepto", "aceptamos", "de acuerdo", "perfecto", "excelente",
    "avancemos", "avanzamos", "firmamos", "procedamos", "me parece bien",
    "vamos adelante", "conforme",
)
_KW_RECHAZO = (
    "no nos interesa", "descartad", "no vamos a avanzar",
    "no seguiremos", "cerramos el tema", "definitivamente no",
    "queda descartada", "rechazamos",
)
_KW_PRECIO = (
    "precio", "caro", "costo", "coste", "presupuesto", "barato",
    "descuento", "rebaja", "invertir", "plata",
)
_KW_TIEMPO = (
    "plazo", "semanas", "demora", "tardar", "urgent", "cuándo",
    "antes de que",
)
_KW_ALCANCE = (
    "alcance", "menos", "simplificar", "funcionalidad", "incluye",
    "módulo", "reducir",
)


def _cliente(api_key: Optional[str] = None) -> genai.Client:
    """Cliente Gemini (SDK nuevo); misma GOOGLE_API_KEY que el resto."""
    clave = api_key or os.getenv("GOOGLE_API_KEY")
    if not clave:
        raise ValueError(
            "Google API key requerida: define GOOGLE_API_KEY en .env."
        )
    return genai.Client(api_key=clave)


@traceable(name="seguimiento-comercial.clasificar", run_type="tool")
def clasificar_objecion(texto: str) -> str:
    """
    Clasificación determinística (terminales primero, luego específicas,
    'otra' como fallback). Devuelve una de:
    aceptacion | rechazo_definitivo | precio | tiempo | alcance | otra
    """
    bajo = (texto or "").lower()
    if any(k in bajo for k in _KW_ACEPTACION):
        return "aceptacion"
    if any(k in bajo for k in _KW_RECHAZO):
        return "rechazo_definitivo"

    # Cifra monetaria explícita (escala CLP / formato punto-de-miles) ⇒
    # objeción de precio, aunque no use la palabra 'precio'. Los plazos
    # (semanas) nunca alcanzan esta magnitud, así que no hay colisión.
    numeros = _extraer_enteros(bajo)
    if any(n >= 100_000 for n in numeros) or re.search(
        r"\d{1,3}(?:\.\d{3})+", bajo
    ):
        return "precio"

    if any(k in bajo for k in _KW_PRECIO):
        return "precio"
    if any(k in bajo for k in _KW_TIEMPO):
        return "tiempo"
    if any(k in bajo for k in _KW_ALCANCE):
        return "alcance"
    return "otra"


def _extraer_enteros(texto: str) -> List[int]:
    """Extrae enteros colapsando separadores de miles con punto (3.500.000)."""
    normalizado = re.sub(r"(?<=\d)\.(?=\d{3}(?:\D|$))", "", texto or "")
    return [int(n) for n in re.findall(r"\d+", normalizado)]


# ─────────────────────────────────────────────────────────────────────────────
# Estado de la negociación
# ─────────────────────────────────────────────────────────────────────────────
def _estado_desde(
    propuesta: Dict[str, Any],
    estado_previo: Optional[Dict[str, Any]],
    catalogo: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Estado corriente de la oferta (tier/precio/tiempo/margen/historial)."""
    if estado_previo:
        estado = dict(estado_previo)
        estado.setdefault("historial", [])
        return estado

    interna = propuesta.get("propuesta_interna_validada") or {}
    margen = float(
        (interna.get("datos_clave") or {}).get(
            "margen_bruto", pc.MARGEN_BRUTO_DEFECTO
        )
    )
    tier_inicial = int(propuesta.get("tier_recomendado", 1))
    entrada = pc._entrada_tier(catalogo, tier_inicial)
    return {
        "tier": tier_inicial,
        "precio_clp": list(propuesta.get("rango_precio_clp") or pc._rango_precio(entrada)),
        "tiempo_semanas": list(propuesta.get("tiempo_estimado_semanas") or pc._tiempo(entrada)),
        "margen": margen,
        "historial": [],
    }


def _paquete_ajuste(
    tier: int,
    entrada: Dict[str, Any],
    precio: Tuple[int, int],
    semanas: Tuple[int, int],
) -> Dict[str, Any]:
    """Forma 'ajuste_propuesto' del esquema de salida."""
    return {
        "tier": int(tier),
        "nombre_tier": entrada.get("nombre", ""),
        "precio_clp": [int(precio[0]), int(precio[1])],
        "tiempo_semanas": [int(semanas[0]), int(semanas[1])],
        "alcance": entrada.get("alcance", ""),
    }


@traceable(name="seguimiento-comercial.ajuste", run_type="tool")
def calcular_ajuste(
    tipo_objecion: str,
    texto_cliente: str,
    estado: Dict[str, Any],
    catalogo: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Motor determinístico de ajuste para objeciones precio/tiempo/alcance.

    PISOS DUROS aplicados aquí (nunca en prompt): ningún valor ofertable
    queda por debajo del mínimo del tier correspondiente; si el pedido es
    menor que el piso, se baja UN tier (si calza) o se contraoferta el piso.
    """
    tier_actual = int(estado["tier"])
    entrada = pc._entrada_tier(catalogo, tier_actual)
    assert entrada is not None, f"Tier {tier_actual} inexistente en catálogo"
    p_min, p_max = pc._rango_precio(entrada)
    s_min, s_max = pc._tiempo(entrada)
    numeros = _extraer_enteros(texto_cliente)

    def bajar_tier() -> Optional[Dict[str, Any]]:
        if tier_actual <= 1:
            return None
        inferior = pc._entrada_tier(catalogo, tier_actual - 1)
        return {"tier": tier_actual - 1, "entrada": inferior} if inferior else None

    if tipo_objecion == "precio":
        objetivo = max(numeros) if numeros else None
        if objetivo is not None and objetivo < p_min:
            baja = bajar_tier()
            if baja is not None:
                b_ent = baja["entrada"]
                b_min, b_max = pc._rango_precio(b_ent)
                precio_oferta = min(max(objetivo, b_min), b_max)
                nota = (
                    f"Pedido ${objetivo} bajo el piso del tier {tier_actual} "
                    f"(${p_min}): se BAJA al tier {baja['tier']} "
                    f"(piso ${b_min})."
                )
                return {
                    "ajuste_propuesto": _paquete_ajuste(
                        baja["tier"],
                        b_ent,
                        (precio_oferta, precio_oferta),
                        pc._tiempo(b_ent),
                    ),
                    "nuevo_tier": baja["tier"],
                    "nota": nota,
                }
            nota = (
                f"Pedido ${objetivo} por debajo del piso del tier "
                f"{tier_actual}: se contraoferta el MÍNIMO ${p_min} "
                "(no negociable hacia abajo)."
            )
            return {
                "ajuste_propuesto": _paquete_ajuste(
                    tier_actual,
                    entrada,
                    (p_min, p_min),
                    (s_min, s_max),
                ),
                "nuevo_tier": tier_actual,
                "nota": nota,
            }
        if objetivo is None or objetivo > p_max:
            precio_oferta = p_min  # gesto de flexibilidad: piso del rango
            nota = (
                f"Sin cifra concreta viable: se ofrece el mínimo del tier "
                f"(${p_min})."
            )
        else:
            precio_oferta = objetivo
            nota = f"Cifra pedida (${objetivo}) está DENTRO del rango del tier."
        return {
            "ajuste_propuesto": _paquete_ajuste(
                tier_actual,
                entrada,
                (precio_oferta, precio_oferta),
                (s_min, s_max),
            ),
            "nuevo_tier": tier_actual,
            "nota": nota,
        }
    if tipo_objecion == "tiempo":
        objetivo = min(numeros) if numeros else None
        if objetivo is not None and objetivo < s_min:
            baja = bajar_tier()
            if baja is not None:
                b_ent = baja["entrada"]
                bs_min, bs_max = pc._tiempo(b_ent)
                semanas_oferta = max(min(objetivo, bs_max), bs_min)
                nota = (
                    f"Plazo pedido ({objetivo} sem.) bajo el mínimo del tier "
                    f"{tier_actual} ({s_min} sem.): se BAJA al tier "
                    f"{baja['tier']} (mínimo {bs_min} sem.)."
                )
                return {
                    "ajuste_propuesto": _paquete_ajuste(
                        baja["tier"],
                        b_ent,
                        pc._rango_precio(b_ent),
                        (semanas_oferta, semanas_oferta),
                    ),
                    "nuevo_tier": baja["tier"],
                    "nota": nota,
                }
            nota = (
                f"Plazo imposible ({objetivo} sem. < mínimo {s_min} sem.): "
                f"se contraoferta el MÍNIMO de semanas ({s_min})."
            )
            return {
                "ajuste_propuesto": _paquete_ajuste(
                    tier_actual, entrada, (p_min, p_max), (s_min, s_min)
                ),
                "nuevo_tier": tier_actual,
                "nota": nota,
            }
        if objetivo is None or objetivo > s_max:
            semanas_oferta = s_min
            nota = (
                f"Sin plazo concreto viable: se ofrece el mínimo de semanas "
                f"({s_min})."
            )
        else:
            semanas_oferta = objetivo
            nota = f"Plazo pedido ({objetivo} sem.) alcanzable dentro del tier."
        return {
            "ajuste_propuesto": _paquete_ajuste(
                tier_actual,
                entrada,
                (p_min, p_max),
                (semanas_oferta, semanas_oferta),
            ),
            "nuevo_tier": tier_actual,
            "nota": nota,
        }

    if tipo_objecion == "alcance":
        baja = bajar_tier()
        if baja is None:
            return {
                "ajuste_propuesto": None,
                "nuevo_tier": tier_actual,
                "accion_especial": "alcance_ya_minimo",
                "nota": (
                    "El cliente pide MENOS alcance pero ya estamos en el tier "
                    "mínimo del catálogo; se explica el alcance mínimo y se "
                    "sugiere dividir el trabajo en fases."
                ),
            }
        b_ent = baja["entrada"]
        nota = (
            "El cliente pide menos alcance: se propone BAJAR al tier "
            f"{baja['tier']} con su alcance y rangos completos."
        )
        return {
            "ajuste_propuesto": _paquete_ajuste(
                baja["tier"],
                b_ent,
                pc._rango_precio(b_ent),
                pc._tiempo(b_ent),
            ),
            "nuevo_tier": baja["tier"],
            "nota": nota,
        }

    raise ValueError(
        f"calcular_ajuste() solo negocia precio/tiempo/alcance; recibió: "
        f"{tipo_objecion}"
    )


@traceable(name="seguimiento-comercial.redactar", run_type="tool")
def _redactar_respuesta_gemini(cliente: genai.Client, prompt: str) -> str:
    """Gemini redacta la respuesta desde el brief cerrado (sin tools).
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
    if respuesta is None:
        raise ultimo_error  # type: ignore[misc]
    return respuesta.text or ""


@traceable(name="seguimiento_comercial", run_type="chain")
def negociar_ronda(
    propuesta: Dict[str, Any],
    respuesta_cliente: str,
    ronda: int = 1,
    estado_previo: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Procesa UNA ronda de negociación y devuelve el JSON de salida.

    Puertas duras aplicadas ANTES de cualquier redacción:
      · ronda >= RONDAS_MAXIMAS sin acuerdo → intervención humana.
      · tipo 'otra' → intervención humana inmediata (fuera de catálogo),
        sin llamar a decidirCEO ni proponer ajustes.
    """
    empresa = str(propuesta.get("empresa", "prospecto"))
    validacion_origen = propuesta.get("validacion_ceo") or {}
    referencia = {
        "run_id_ceo": validacion_origen.get("run_id"),
        "langsmith_url_ceo": validacion_origen.get("langsmith_url"),
    }

    catalogo = pc.cargar_catalogo()
    estado = _estado_desde(propuesta, estado_previo, catalogo)
    historial: List[Dict[str, Any]] = list(estado.get("historial") or [])
    tipo = clasificar_objecion(respuesta_cliente)

    base = {
        "empresa": empresa,
        "ronda": int(ronda),
        "tipo_objecion": tipo,
        "ajuste_propuesto": None,
        "validacion_ceo": None,
        "referencia_propuesta_origen": referencia,
    }
    fallo_redaccion = None

    def _salida(
        requiere_humano: bool,
        texto: str,
        ajuste: Optional[Dict[str, Any]] = None,
        validacion: Optional[Dict[str, Any]] = None,
        nota: str = "",
        estado_nuevo: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        historial.append(
            {
                "ronda": int(ronda),
                "tipo_objecion": tipo,
                "nota": nota or ("escalamiento a humano" if requiere_humano else ""),
                "requiere_intervencion_humana": requiere_humano,
            }
        )
        salida = {**base, "requiere_intervencion_humana": requiere_humano}
        if ajuste is not None:
            salida["ajuste_propuesto"] = ajuste
        if validacion is not None:
            salida["validacion_ceo"] = validacion
        salida["respuesta_texto"] = texto
        salida["historial_ronda"] = historial
        if estado_nuevo is not None:
            salida["estado_negociacion"] = estado_nuevo
        if fallo_redaccion:
            salida["error_redaccion"] = fallo_redaccion
        return salida

    # ── Terminales ────────────────────────────────────────────────────────
    def _cierre(caso_plantilla: str, decision_tomada: str) -> Dict[str, Any]:
        nonlocal fallo_redaccion
        texto = ""
        try:
            texto = _redactar_respuesta_gemini(
                _cliente(api_key),
                _construir_brief(
                    empresa, tipo, ronda, decision_tomada, None, None, ""
                ),
            )
        except Exception as exc:  # noqa: BLE001
            fallo_redaccion = str(exc)[:200]  # type: ignore[assignment]
        if not texto.strip():
            texto = _PLANTILLAS[caso_plantilla].format(empresa=empresa)
        return _salida(False, texto)

    if tipo == "aceptacion":
        return _cierre("cierre_aceptacion", "cierre por aceptación")
    if tipo == "rechazo_definitivo":
        return _cierre("cierre_rechazo", "cierre por rechazo definitivo")

    # ── Fuera de catálogo: intervención INMEDIATA (sin CEO, sin ajustes) ──
    if tipo == "otra":
        return _salida(
            True,
            _PLANTILLAS["escalado_otra"].format(empresa=empresa),
            nota="objeción fuera de catálogo ⇒ escalamiento inmediato",
        )

    # ── Límite DURO de rondas ─────────────────────────────────────────────
    if int(ronda) >= RONDAS_MAXIMAS:
        resumen = (
            f"Negociación con {empresa}: {len(historial)} ronda(s) previa(s) "
            f"sin acuerdo; en la ronda {ronda} persiste la objeción "
            f"'{tipo}'. Se detiene la negociación automática."
        )
        return _salida(
            True,
            _PLANTILLAS["escalado_limite_rondas"].format(empresa=empresa),
            nota=resumen,
        )

    # ── Negociación normal (precio / tiempo / alcance) ────────────────────
    decision = calcular_ajuste(tipo, respuesta_cliente, estado, catalogo)
    ajuste = decision.get("ajuste_propuesto")

    if ajuste is None:
        # p.ej. alcance ya está en el tier mínimo: se explica, sin CEO
        texto = ""
        try:
            texto = _redactar_respuesta_gemini(
                _cliente(api_key),
                _construir_brief(
                    empresa,
                    tipo,
                    ronda,
                    "explicar que ya se ofrece el alcance mínimo y sugerir fases",
                    None,
                    None,
                    decision.get("nota", ""),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            fallo_redaccion = str(exc)[:200]
        if not texto.strip():
            texto = _PLANTILLAS["alcance_ya_minimo"].format(empresa=empresa)
        return _salida(False, texto, nota=decision.get("nota", ""))

    # El monto/alcance cambia ⇒ REVALIDACIÓN obligatoria vía decidirCEO()
    seleccion_equivalente = {
        "tier_principal": ajuste["tier"],
        "nombres": ajuste.get("nombre_tier", ""),
        "entradas": [pc._entrada_tier(catalogo, ajuste["tier"])],
        "rango_precio_clp": ajuste["precio_clp"],
        "tiempo_estimado_semanas": ajuste["tiempo_semanas"],
        "requiere_llamada_diagnostico": False,
    }
    interna = pc._construir_propuesta_interna(
        {"empresa": empresa},
        seleccion_equivalente,
        float(estado.get("margen", pc.MARGEN_BRUTO_DEFECTO)),
    )
    try:
        validacion = pc.validar_con_decidir_ceo(interna)
    except Exception as exc:  # noqa: BLE001
        validacion = {
            "decision": "error",
            "lista_para_enviar": False,
            "detalle": str(exc)[:300],
            "run_id": None,
            "langsmith_url": None,
        }

    if not validacion.get("lista_para_enviar"):
        # El CEO bloqueó el ajuste ⇒ NO se ofrece al cliente; se escala.
        return _salida(
            True,
            _PLANTILLAS["escalado_ceo_bloqueo"].format(empresa=empresa),
            ajuste=ajuste,
            validacion=validacion,
            nota=f"decidirCEO bloqueó el ajuste ({validacion.get('decision')})",
        )

    # Ajuste APROBADO por el CEO ⇒ redactar la oferta concreta
    try:
        texto = _redactar_respuesta_gemini(
            _cliente(api_key),
            _construir_brief(
                empresa,
                tipo,
                ronda,
                "ofrecer el siguiente ajuste aprobado internamente",
                ajuste,
                validacion,
                decision.get("nota", ""),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        texto = ""
        fallo_redaccion = str(exc)[:200]

    if not texto.strip():
        precio = ajuste["precio_clp"]
        semanas = ajuste["tiempo_semanas"]
        texto = (
            f"Hola {empresa},\n\nEntendemos tu punto sobre el {tipo}. "
            f"Podemos ajustarnos así: tier {ajuste['tier']} "
            f"({ajuste.get('nombre_tier', '')}), inversión entre $CLP "
            f"{precio[0]} y {precio[1]}, en {semanas[0]}-{semanas[1]} "
            "semanas.\n\n¿Te funciona para cerrarlo?\n\nEquipo EUREKA"
        )

    estado_nuevo = {
        "tier": ajuste["tier"],
        "precio_clp": ajuste["precio_clp"],
        "tiempo_semanas": ajuste["tiempo_semanas"],
        "margen": float(estado.get("margen", pc.MARGEN_BRUTO_DEFECTO)),
        "historial": historial
        + [
            {
                "ronda": int(ronda),
                "tipo_objecion": tipo,
                "nota": decision.get("nota", ""),
                "requiere_intervencion_humana": False,
            }
        ],
    }
    return _salida(
        False,
        texto,
        ajuste=ajuste,
        validacion=validacion,
        nota=decision.get("nota", ""),
        estado_nuevo=estado_nuevo,
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Agente de Seguimiento Comercial EUREKA"
    )
    parser.add_argument("propuesta", help="JSON de propuestas-comerciales.py")
    parser.add_argument(
        "respuesta", help="Texto libre de objeción/respuesta del cliente"
    )
    parser.add_argument("--ronda", type=int, default=1)
    parser.add_argument("--estado", help="JSON opcional con estado_previo")
    args = parser.parse_args()

    with open(args.propuesta, "r", encoding="utf-8") as fh:
        propuesta = json.load(fh)
    estado_previo = None
    if args.estado:
        with open(args.estado, "r", encoding="utf-8") as fh:
            estado_previo = json.load(fh)

    resultado = negociar_ronda(
        propuesta,
        args.respuesta,
        ronda=args.ronda,
        estado_previo=estado_previo,
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

    raise ValueError(f"Tipo de objeción no negociable aquí: {tipo_objecion}")


# ─────────────────────────────────────────────────────────────────────────────
# Redacción de la respuesta al cliente
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres el ejecutivo de seguimiento comercial de EUREKA \
(agentes y multiagentes de IA a medida).

Recibirás un BRIEF con: empresa, tipo de objeción del cliente, la DECISIÓN ya \
tomada por el sistema (mantener oferta / ofrecer un ajuste concreto con sus \
cifras / bajar de tier / escalar a humano), los valores finales aprobados y \
los pisos que NO se pueden cruzar.

REGLAS ABSOLUTAS:
1. Cifras, plazos y tiers: SOLO los del brief. PROHIBIDO inventar descuentos, \
extender alcances o prometer plazos distintos.
2. Si el brief dice que se escala a humano: explica con transparencia que un \
ejecutivo senior tomará el caso personalmente en menos de 24 horas hábiles. \
NO des contrapropuestas.
3. Si el brief indica cierre por aceptación: agradece y lista los próximos \
pasos administrativos (orden de compra, anticipo y kickoff).
4. Si el brief indica rechazo definitivo: agradece con profesionalismo y deja \
la puerta abierta, sin insistir.
5. Empatía primero: valida la preocupación del cliente antes de responder.
6. Español, 3-6 párrafos cortos como máximo. Responde ÚNICAMENTE con el \
texto listo para enviar al cliente."""

_PLANTILLAS = {
    "escalado_otra": (
        "Hola {empresa},\n\nGracias por compartir tu punto de vista. Tu "
        "consulta sale del alcance de nuestros planes estándar, así que para "
        "responderte con precisión (y sin prometer de más) la derivaré a un "
        "ejecutivo senior de EUREKA, que te contactará en menos de 24 horas "
        "hábiles.\n\nUn saludo,\nEquipo EUREKA"
    ),
    "escalado_limite_rondas": (
        "Hola {empresa},\n\nAgradecemos la conversación hasta aquí. Para no "
        "seguir proponiendo alternativas que podrían alejarse de lo que "
        "necesitas, preferimos que un ejecutivo senior de EUREKA tome tu "
        "caso personalmente y busquemos juntos el camino correcto.\n\nTe "
        "contactará en menos de 24 horas hábiles.\n\nUn saludo,\nEquipo EUREKA"
    ),
    "escalado_ceo_bloqueo": (
        "Hola {empresa},\n\nAgradecemos tu frankness: tomamos nota de tu "
        "punto. La alternativa que consideramos requiere una revisión "
        "interna adicional antes de poder comprometerla, así que un "
        "ejecutivo senior te contactará en menos de 24 horas hábiles con una "
        "respuesta definitiva.\n\nUn saludo,\nEquipo EUREKA"
    ),
    "cierre_aceptacion": (
        "¡Excelente, {empresa}! 🎉\n\nEntonces dejamos fijados los próximos "
        "pasos: 1) enviamos la orden de compra y el contrato para firma; "
        "2) coordinamos el pago del anticipo; 3) agendamos el kickoff con "
        "el equipo.\n\n¡Bienvenidos a este proyecto junto a EUREKA!"
    ),
    "cierre_rechazo": (
        "Hola {empresa},\n\nAgradecemos sinceramente el tiempo y la "
        "transparencia. Respetamos totalmente la decisión. Si en el futuro "
        "el contexto cambia, estaremos a un mensaje de distancia.\n\nÉxitos "
        "para el equipo.\nEquipo EUREKA"
    ),
    "alcance_ya_minimo": (
        "Hola {empresa},\n\nTiene sentido reducir el alcance para arrancar "
        "más livianos: de hecho, el plan que te propuse YA es el formato más "
        "compacto de nuestro catálogo. Una alternativa que suele funcionar "
        "es dividirlo en fases cortas, priorizando primero el caso de uso "
        "de mayor impacto y evolucionando sobre resultados.\n\n¿Agendamos "
        "15 minutos para definir esa primera fase?\n\nUn saludo,\nEquipo EUREKA"
    ),
}


def _construir_brief(
    empresa: str,
    tipo_objecion: str,
    ronda: int,
    decision_tomada: str,
    ajuste: Optional[Dict[str, Any]],
    validacion: Optional[Dict[str, Any]],
    nota: str,
) -> str:
    """Brief cerrado para que Gemini redacte la respuesta (sin inventar nada)."""
    partes = [
        "BRIEF DE RESPUESTA A OBJECIÓN",
        f"Empresa: {empresa}",
        f"Ronda de negociación: {ronda}",
        f"Objeción clasificada: {tipo_objecion}",
        f"Decisión tomada por el sistema: {decision_tomada}",
    ]
    if nota:
        partes.append(f"Detalle interno de la decisión: {nota}")
    if ajuste:
        partes.append(
            "Oferta a comunicar (cifras EXACTAS): "
            f"tier {ajuste.get('tier')} · {ajuste.get('nombre_tier','')}; "
            f"precio $CLP {ajuste['precio_clp'][0]} a {ajuste['precio_clp'][1]}; "
            f"plazo {ajuste['tiempo_semanas'][0]}-{ajuste['tiempo_semanas'][1]} semanas; "
            f"alcance: {ajuste.get('alcance','')}"
        )
    if validacion:
        partes.append(
            f"Validación interna decidirCEO: {validacion.get('decision')} — "
            f"{str(validacion.get('detalle',''))[:200]}"
        )
    partes.append(
        "Pisos inviolables que NO deben mencionarse como negociables: los "
        "mínimos de precio y plazo del catálogo."
    )
    partes.append("Redacta la respuesta siguiendo las REGLAS.")
    return "\n".join(partes)