/**
 * E2E - Ejecuta el ciclo CEO completo de EUREKA cargando .env (trazas activas).
 *
 * Uso:
 *   node scripts/e2e.js [--json] [gemini]
 *
 *   - Sin argumentos: ejecuta el ciclo completo con salida legible (stored).
 *   - Con  'gemini' : además lanza el agente Python (subproceso) como span anidado.
 *   - Con  '--json' : imprime UN SOLO objeto JSON en stdout. Todos los logs de
 *                     progreso van a stderr (requerido para la UI Streamlit).
 *
 * La propuesta se carga, en orden de precedencia:
 *   1. Variable de entorno EUREKA_PROPUESTA_JSON (JSON string) — usada por
 *      eureka_agent_bridge.py y por app_streamlit.py.
 *   2. --propuesta <archivo-json> (existe ejemplos/propuestas.json).
 *   3. Propuesta de ejemplo fija (legado).
 */
const path = require('path');
const fs = require('fs');

// Cargar .env ANTES de que cualquier traceable cree su primer run.
// quiet:true para que dotenv no escriba su banner en stdout (en modo --json
// stdout debe contener ÚNICAMENTE el objeto JSON).
const root = process.cwd();
process.chdir(root);
require(path.join(root, 'node_modules', 'dotenv')).config({ path: path.join(root, '.env'), quiet: true });

const { CEO } = require(path.join(root, 'dist', 'core', 'ceo'));

const args = process.argv.slice(2);
const jsonMode = args.includes('--json');
const conGemini = args.includes('gemini');

// En modo --json, cualquier log de progreso debe ir a stderr para no
// contaminar el JSON de stdout.
const log = (...mensajes) => {
  if (jsonMode) {
    console.error(...mensajes);
  } else {
    console.log(...mensajes);
  }
};

function propuestaPorDefecto() {
  return {
    agente: 'ventas',
    tipo: 'propuesta',
    resumen: 'Promoción de verano con descuentos',
    datos_clave: {
      margen_bruto: 20,
      crecimiento_ventas: 20,
      ventas_actuales: 10_000_000,
      caja_proyectada: 60_000_000,
      caja_actual: 70_000_000
    },
    riesgo: 'medio',
    requiere_aprobacion_ceo: true
  };
}

function cargarPropuesta() {
  // 1. Variable de entorno (método principal usado por Streamlit)
  if (process.env.EUREKA_PROPUESTA_JSON) {
    try {
      return JSON.parse(process.env.EUREKA_PROPUESTA_JSON);
    } catch (err) {
      log('Aviso: EUREKA_PROPUESTA_JSON no es JSON válido -', err.message);
    }
  }
  // 2. --propuesta <archivo>
  const idx = args.indexOf('--propuesta');
  if (idx !== -1 && args[idx + 1]) {
    try {
      const raw = fs.readFileSync(args[idx + 1], 'utf8');
      return JSON.parse(raw);
    } catch (err) {
      log('Aviso: no se pudo leer la propuesta desde archivo -', err.message);
    }
  }
  return propuestaPorDefecto();
}

function construirAportes(decision) {
  const mapa = {};
  for (const aporte of decision.aportes_agentes || []) {
    mapa[aporte.agente] = aporte.resultado;
  }
  return mapa;
}

function construirAportesGemini(aportesGemini) {
  if (!aportesGemini) return null;
  if (aportesGemini.error) {
    return { context: null, validation: null, error: aportesGemini.error };
  }
  return {
    context: aportesGemini.contexto_utilizado || null,
    validation: aportesGemini.validacion_financiera_gemini || null,
    error: null
  };
}

(async () => {
  const propuesta = cargarPropuesta();

  log('=== E2E EUREKA CEO Orchestrator (trazas LangSmith) ===');
  log(`Modo: ${jsonMode ? 'json' : 'humano'} | ${conGemini ? 'con Gemini (Python)' : 'solo agentes TS'}`);
  log('Propuesta:', propuesta.resumen, `(${propuesta.agente})`);

  const decision = await CEO.tomarDecision(propuesta, [], { ejecutarGemini: conGemini });

  // trade_off explícito (viene de observaciones_ventas del agente ventas-observador)
  const tradeOff = (decision.observaciones_ventas && decision.observaciones_ventas.tradeOff) ||
    (construirAportes(decision)['ventas-observador'] || {}).tradeOff || '';

  // Generar el link directo al run en LangSmith (con reintentos por latencia)
  let langsmithUrl = null;
  if (decision.run_id) {
    try {
      const { Client } = require('langsmith');
      const client = new Client();
      const projectName = process.env.LANGCHAIN_PROJECT || 'eureka-agents';
      for (let intento = 0; intento < 3; intento += 1) {
        try {
          langsmithUrl = await client.getRunUrl({ runId: decision.run_id, projectOpts: { projectName } });
          if (langsmithUrl) break;
        } catch {
          if (intento < 2) await new Promise((r) => setTimeout(r, 1200));
        }
      }
    } catch (err) {
      console.error('No se pudo generar el link LangSmith:', err.message);
    }
  }

  if (jsonMode) {
    const payload = {
      decision: decision.decision,
      justificacion: decision.justificacion,
      trade_off: tradeOff || '',
      run_id: decision.run_id || null,
      langsmith_url: langsmithUrl || null,
      aportes_agentes: construirAportes(decision),
      aportes_gemini: construirAportesGemini(decision.aportes_gemini)
    };
    // ÚNICA salida en stdout en modo JSON
    console.log(JSON.stringify(payload));
  } else {
    log('');
    log('Decisión:', decision.decision);
    log('Justificación:', decision.justificacion);
    log('run_id:', decision.run_id || '(sin tracing - cargaste .env?)');
    log('spans agentes:', (decision.aportes_agentes || []).map((a) => a.agente).join(', '));
    if (langsmithUrl) log('LINK_TRAZA:', langsmithUrl);
    else console.log('run_id (abre el proyecto en LangSmith y búscalo):', decision.run_id);
  }

  // Esperar un instante para que LangSmith termine de indexar los spans
  await new Promise((r) => setTimeout(r, 800));
  process.exit(0);
})().catch((e) => {
  console.error('E2E falló:', e);
  process.exit(1);
});