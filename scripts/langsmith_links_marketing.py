#!/usr/bin/env python3
"""Muestra los runs recientes de marketing_prospeccion en LangSmith y sus enlaces."""
import sys
import warnings

from dotenv import load_dotenv

load_dotenv()

# Consola Windows (cp1252): salida UTF-8 tolerante para símbolos del árbol
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# langsmith>=0.11 marca list_runs/get_run_url como deprecated (migración a
# client.runs.query/get_url tras ene-2027); aquí siguen siendo las llamadas
# funcionales — silenciamos el aviso solo en este script diagnóstico.
warnings.filterwarnings("ignore", category=DeprecationWarning)

import os  # noqa: E402

from langsmith import Client  # noqa: E402


def _enlace(c: Client, r) -> str:
    for intento in (
        lambda: c.get_run_url(run=r),
        lambda: c.get_run_url(run_id=r.id, project_name=os.getenv("LANGCHAIN_PROJECT")),
    ):
        try:
            return intento()
        except Exception:
            continue
    proj = os.getenv("LANGCHAIN_PROJECT") or "default"
    return (
        f"(sin enlace directo — búscalo por id={r.id} en "
        f"https://smith.langchain.com/projects/p/{proj})"
    )


def main() -> None:
    c = Client()
    proj = os.getenv("LANGCHAIN_PROJECT") or "default"
    nombre_raiz = sys.argv[1] if len(sys.argv) > 1 else "marketing_prospeccion"
    print("PROYECTO LANGSMITH:", proj)
    print("RAÍZ BUSCADA:", nombre_raiz)

    raices = list(
        c.list_runs(
            project_name=proj,
            filter=f'eq(name, "{nombre_raiz}")',
            limit=3,
        )
    )
    if not raices:
        print("Sin runs de marketing_prospeccion todavía.")
        return
    for r in raices:
        print(f"\nROOT {r.name} · {str(r.start_time)[:19]} · id={r.id}")
        entrada = str(getattr(r, "inputs", "") or "")
        print("  INPUT:", entrada[:120])
        print("  ENLACE:", _enlace(c, r))
        hijos = list(c.list_runs(project_name=proj, run_id=r.id, limit=10))
        for h in hijos:
            print(f"   └─ span: {h.name} | error={'sí' if h.error else 'no'}")


if __name__ == "__main__":
    main()