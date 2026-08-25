# EUREKA Agents - CEO Orchestrator

Sistema de orquestación de decisiones para la empresa EUREKA (rubro: creación de agentes).

## Contexto de la empresa

- **Objetivo trimestral:** Margen bruto > 25%, crecimiento en ventas +15% QoQ
- **Restricciones duras:** Caja mínima $50M, límite de deuda $200M
- **Umbral de escalamiento:** Montos > $100M, riesgo legal, conflictos irresolubles
- **Valores no negociables:** No vender bajo costo, cumplir plazos legales

## Arquitectura

```
src/
├── types/          # Tipos TypeScript
├── config/         # Configuración de la empresa y carga de .env
├── agents/         # Lógica de validación por agente (spans de traza)
├── core/           # Motor de decisión CEO (run padre de la traza)
└── index.ts        # CLI interactiva
```

## Uso

1. Instalar dependencias:
```bash
npm install
```

2. Ejecutar en modo desarrollo:
```bash
npm run dev
```

3. Ejecutar pruebas:
```bash
npm test
```

4. Verificación puntual de trazabilidad (sin modo interactivo):
```bash
node scripts/e2e.js            # árbol con los 5 agentes TS
node scripts/e2e.js gemini     # además los spans del agente Python de Gemini
```

## Formato de propuestas

```typescript
{
  "agente": "finanzas|logistica|compras|ventas",
  "tipo": "propuesta|alerta|reporte",
  "resumen": "string",
  "datos_clave": {...},
  "riesgo": "bajo|medio|alto",
  "requiere_aprobacion_ceo": true|false
}
```

## Reglas de decisión

1. Nunca aprobar sin cruzar datos de al menos otro agente (el CEO siempre ejecuta los 5 agentes)
2. Priorizar: caja > legal > objetivos > operativo
3. Escalar cuando se supera el umbral o hay riesgo legal
4. Declarar explícitamente el trade-off en cada decisión
5. Ningún aporte inválido se ignora: la objeción del agente origen rechaza la propuesta; la objeción de otro agente base (o una alerta crítica del observador) fuerza escalamiento a humano
6. La recomendación del ventas-observador siempre se honra: `solicitar_ajustes` → reformular con sus mejoras como condiciones; `escalar`/`rechazar` → escalamiento/rechazo

## Agente de Marketing / Prospección (nueva línea de ventas)

`src/agents/marketing-prospeccion.py` — primer agente de la línea de venta
de agentes/multiagentes de IA a medida para pymes y grandes empresas.

**Arquitectura en dos fases** (reemplaza al grounding nativo de Gemini):

1. **Búsqueda web con Tavily** — trae snippets y URLs reales sobre la empresa.
2. **Redacción con Gemini (`gemini-3.6-flash`)** — recibe esos resultados
   embebidos en el prompt y redacta el dossier SOLO con ellos (uso de texto,
   gratuito y sin tarjeta).

> **LÍMITE GRATUITO DE LA BÚSQUEDA (Tavily):** plan Free de **1.000 créditos/mes,
> SIN tarjeta de crédito** (se resetea el día 1 de cada mes). Una investigación
> de empresa = 1 búsqueda `basic` = 1 crédito ⇒ **~1.000 empresas/mes**
> (~33/día de media). Clave gratuita en <https://app.tavily.com> → variable
> `TAVILY_API_KEY` en `.env`.

Política anti-alucinación: `fuentes` = EXCLUSIVAMENTE las URLs devueltas por
la búsqueda (lo que el modelo declare se ignora); datos sin evidencia =
`"no encontrado"`; sin fuentes ⇒ `confianza: "baja"`; perfiles personales de
LinkedIn (`/in/`) descartados por código. Prohibido recolectar datos
personales de empleados.

Uso:

```bash
python src/agents/marketing-prospeccion.py "Mercadona" [rubro]
python tests/test_marketing_prospeccion.py            # offline (mock) + en vivo
```

Trazabilidad LangSmith: run raíz `marketing_prospeccion` + spans hijos
`marketing-prospeccion.busqueda_web` y `marketing-prospeccion.redactar`.
Aún NO conectado a `decidirCEO()` (integración prevista como paso aparte).

## Trazabilidad en LangSmith

El ciclo agéntico completo se publica como UN SOLO árbol de traza por decisión:

```
decidirCEO (raíz)
├── finanzas
├── logistica
├── compras
├── ventas
├── ventas-observador
├── finanzas_calcular_impacto_caja   (cuando la propuesta declara caja)
└── gemini_agent                     (opcional, desde Python)
    ├── get_eureka_context
    ├── validate_financial_proposal
    └── managed_deep_agent_direct    (llamada a Gemini)
```

### ¿Cómo se activa?

- El archivo `.env` debe contener `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`,
  `LANGCHAIN_PROJECT` y `GOOGLE_API_KEY`. `src/index.ts` carga `.env` con `dotenv`
  antes de crear el primer run.
- `src/core/ceo.ts` envuelve `decidirCEO()` con `traceable` (run raíz) e invoca a los
  5 agentes siempre como spans hijos.
- El agente Python (`eureka_agent_bridge.py`) se lanza como subproceso desde Node
  propagando el dotted order (`langsmith-trace`), de modo que sus spans quedan anidados
  bajo el run raíz `decidirCEO` (distributed tracing oficial de LangSmith).
- Al procesar una propuesta la CLI imprime el enlace directo a la traza en LangSmith.