#!/usr/bin/env python3
"""
Prueba del agente de Marketing/Prospección.

PARTE A (offline, sin red): normalización anti-invento, extracción de JSON y
pipeline COMPLETO mockeando la búsqueda (Tavily) y la redacción (Gemini):
'fuentes' deben ser SOLO las URLs devueltas por la búsqueda; cualquier fuente
que declare el modelo se ignora.
PARTE B (en vivo, 2 empresas reales vía búsqueda Tavily + Gemini en modo
texto): dossier bien formado, con fuentes http reales y LinkedIn corporativo
(no personal). Requiere TAVILY_API_KEY en .env (gratis, sin tarjeta); si
falta, se informa como pendiente en vez de romper la suite.

Uso:
    python tests/test_marketing_prospeccion.py              # completa
    python tests/test_marketing_prospeccion.py --solo-offline
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RUTA_AGENTE = RAIZ / "src" / "agents" / "marketing-prospeccion.py"

_spec = importlib.util.spec_from_file_location("marketing_prospeccion", RUTA_AGENTE)
mp = importlib.util.module_from_spec(_spec)
sys.modules["marketing_prospeccion"] = mp
_spec.loader.exec_module(mp)

CLAVES_ESQUEMA = {
    "empresa",
    "rubro",
    "tamano_estimado",
    "presencia_digital",
    "senales_de_necesidad",
    "fuentes",
    "confianza",
}

# Consola Windows (cp1252 al canalizar salida): fuerza UTF-8 tolerante
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(encoding="utf-8", errors="replace")

FALLOS: list = []


def chequear(condicion: bool, mensaje: str) -> None:
    print(f"  {'OK ' if condicion else 'FALLO'} · {mensaje}")
    if not condicion:
        FALLOS.append(mensaje)


# ─────────────────────────────────────────────────────────────────────────────
def parte_a_offline() -> None:
    print("\n== PARTE A · Normalización offline (sin red) ==")

    sucio = {
        "rubro": "  retail ",
        "tamano_estimado": "GIGANTE",  # inválido → no encontrado
        "presencia_digital": {
            "sitio_web": "mercadona.es",  # sin esquema → no encontrado
            "linkedin": "https://linkedin.com/in/alguien",  # persona → fuera
            "extra": "x",
        },
        "senales_de_necesidad": ["sin chatbot en su sitio", "", 42],
        "fuentes": ["nota-de-prensa.pdf", "https://expansion.com/articulo"],
        "confianza": "ALTISIMA",  # inválida → baja
    }
    d = mp._normalizar_dossier(sucio, "Mercadona", ["https://elpais.com/nota"])

    chequear(set(d) == CLAVES_ESQUEMA, "claves EXACTAS del esquema")
    chequear(d["rubro"] == "retail", "rubro recortado de espacios")
    chequear(d["tamano_estimado"] == "no encontrado", "tamaño inventado → no encontrado")
    chequear(
        d["presencia_digital"]["sitio_web"] == "no encontrado",
        "URL sin esquema → no encontrado",
    )
    chequear(
        d["presencia_digital"]["linkedin"] == "no encontrado",
        "LinkedIn PERSONAL (/in/) descartado por política",
    )
    chequear(
        d["senales_de_necesidad"] == ["sin chatbot en su sitio"],
        "señales: lista limpia de strings",
    )
    chequear(
        d["fuentes"] == ["https://elpais.com/nota"],
        "fuentes = SOLO URLs de la búsqueda; lo que declare el modelo se IGNORA",
    )
    chequear(d["confianza"] == "baja", "confianza inválida → baja")

    j = mp._extraer_json('ruido ```json\n{"a": {"b": 1}}\n``` mas ruido')
    chequear(j == {"a": {"b": 1}}, "_extraer_json soporta bloques anidados/markdown")

    # ── Pipeline COMPLETO offline: búsqueda simulada + redacción simulada ────
    busqueda_falsa = {
        "consulta": "Acme empresa",
        "resultados": [
            {
                "titulo": "Acme — sitio oficial",
                "url": "https://acme.com",
                "snippet": "Acme es una pyme industrial fundada en 1990.",
            },
            {
                "titulo": "Resultado secundario",
                "url": "https://directorio.example/acme",
                "snippet": "ficha en directorio B2B",
            },
            {
                # perfil PERSONAL que Tavily pudo devolver → debe filtrarse:
                "titulo": "Perfil de un empleado",
                "url": "https://ar.linkedin.com/in/empleado-acme",
                "snippet": "perfil individual",
            },
        ],
    }
    json_modelo_falso = json.dumps(
        {
            "empresa": "Acme",
            "rubro": "industrial",
            "tamano_estimado": "pyme",
            "presencia_digital": {
                "sitio_web": "https://acme.com",
                # persona → debe descartarse aunque el modelo lo insista:
                "linkedin": "https://linkedin.com/in/persona-acme",
            },
            "senales_de_necesidad": ["sin chatbot visible [fuente: acme.com]"],
            # fuente INVENTADA por el modelo → debe ser IGNORADA por completo:
            "fuentes": ["https://fuente-inventada.net"],
            "confianza": "alta",
        },
        ensure_ascii=False,
    )

    orig_buscar = mp._buscar_web_tavily
    orig_redactar = mp._redactar_dossier_gemini
    try:
        mp._buscar_web_tavily = lambda consulta: busqueda_falsa
        mp._redactar_dossier_gemini = lambda cliente, prompt: json_modelo_falso
        d_mock = mp.investigar_empresa("Acme")
    finally:
        mp._buscar_web_tavily = orig_buscar
        mp._redactar_dossier_gemini = orig_redactar

    chequear(set(d_mock) == CLAVES_ESQUEMA, "pipeline mock: esquema exacto")
    chequear(
        d_mock["fuentes"]
        == ["https://acme.com", "https://directorio.example/acme"],
        "pipeline mock: fuentes = SOLO URLs de búsqueda, SIN /in/ personales;"
        " la inventada se IGNORA",
    )
    chequear(
        d_mock["presencia_digital"]["linkedin"] == "no encontrado",
        "pipeline mock: LinkedIn personal (/in/) descartado de punta a punta",
    )
    chequear(
        d_mock["confianza"] == "alta" and d_mock["tamano_estimado"] == "pyme",
        "pipeline mock: campos válidos del modelo se conservan",
    )

    prompt_mock = mp._construir_prompt("Acme", None, busqueda_falsa)
    chequear(
        "https://acme.com" in prompt_mock and "ÚNICA fuente" in prompt_mock,
        "_construir_prompt embebe los resultados y declara fuente única",
    )

    # Sin TAVILY_API_KEY → dict con error accionable (ni crash ni inventos)
    clave_previa = os.environ.pop("TAVILY_API_KEY", None)
    try:
        d_sin_clave = mp.investigar_empresa("Xyz")
    finally:
        if clave_previa is not None:
            os.environ["TAVILY_API_KEY"] = clave_previa
    chequear(
        set(d_sin_clave) >= {"empresa", "error"}
        and "TAVILY_API_KEY" in d_sin_clave.get("error", ""),
        "sin TAVILY_API_KEY → error accionable, sin dossier inventado",
    )


# ─────────────────────────────────────────────────────────────────────────────
EMPRESAS_VIVO = [
    {"nombre": "Mercadona"},
    {"nombre": "Globant"},
]


def parte_b_en_vivo() -> None:
    print("\n== PARTE B · Empresas reales (búsqueda Tavily + Gemini texto) ==")
    for caso in EMPRESAS_VIVO:
        nombre = caso["nombre"]
        print(f"\n— Investigando: {nombre}")
        d = mp.investigar_empresa(nombre)

        if "error" in d:
            detalle = str(d.get("error"))
            if "TAVILY_API_KEY" in detalle:
                chequear(
                    False,
                    f"[SIN-TAVILY-KEY] {nombre}: pendiente configurar clave "
                    "(gratis en app.tavily.com, 1.000 créditos/mes sin tarjeta)",
                )
            else:
                chequear(False, f"{nombre}: ERROR → {detalle[:140]}")
            continue

        chequear(set(d) == CLAVES_ESQUEMA, f"{nombre}: claves EXACTAS del esquema")
        chequear(d["empresa"] == nombre, f"{nombre}: eco del nombre solicitado")
        chequear(
            d["rubro"] not in ("", "no encontrado"),
            f"{nombre}: rubro inferido ('{d['rubro']}')",
        )
        chequear(
            d["tamano_estimado"] in ("pyme", "grande", "no encontrado"),
            f"{nombre}: tamaño válido ('{d['tamano_estimado']}')",
        )

        presencia = d["presencia_digital"]
        chequear(
            set(presencia) == {"sitio_web", "linkedin"},
            f"{nombre}: presencia_digital con claves exactas",
        )
        chequear(
            presencia["sitio_web"].startswith("http"),
            f"{nombre}: sitio web real ({presencia['sitio_web']})",
        )
        li = presencia["linkedin"]
        chequear(
            li == "no encontrado"
            or ("/in/" not in li and "linkedin.com" in li.lower()),
            f"{nombre}: LinkedIn corporativo o 'no encontrado' ({li})",
        )
        chequear(
            isinstance(d["senales_de_necesidad"], list)
            and all(isinstance(s, str) and s.strip() for s in d["senales_de_necesidad"]),
            f"{nombre}: señales bien tipadas ({len(d['senales_de_necesidad'])})",
        )
        chequear(
            len(d["fuentes"]) >= 1
            and all(str(u).startswith("http") for u in d["fuentes"]),
            f"{nombre}: ≥1 fuente http real ({len(d['fuentes'])} fuentes)",
        )
        chequear(
            len(set(d["fuentes"])) == len(d["fuentes"]),
            f"{nombre}: fuentes sin duplicados",
        )
        chequear(
            d["confianza"] in ("alta", "media", "baja"),
            f"{nombre}: confianza válida ('{d['confianza']}')",
        )

        print(json.dumps(d, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parte_a_offline()
    if "--solo-offline" not in sys.argv:
        parte_b_en_vivo()

    print("\n================ RESULTADO ================")
    if FALLOS:
        print(f"FALLOS ({len(FALLOS)}):")
        for f in FALLOS:
            print(" -", f)
        sys.exit(1)
    print("TODOS LOS CHEQUEOS PASARON")