import { CEO, OpcionesDecision } from './core/ceo';
import { Propuesta } from './types/agent';
import { cargarEnv, isTracingEnabled } from './config/env';
import { Client } from 'langsmith';
import * as readline from 'readline';

// Cargar .env ANTES de que cualquier traceable cree su primer run
cargarEnv();

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

function mostrarMenu() {
  console.log('\n=== EUREKA CEO Orchestrator ===');
  console.log('1. Ingresar propuesta manualmente');
  console.log('2. Cargar ejemplo de propuesta');
  console.log('3. Salir');
  console.log('4. Ejemplo con evaluación del agente Gemini (Python)');
  console.log('\nSeleccione una opción:');
}

function propuestaEjemplo(): Propuesta {
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

async function linkTraza(runId?: string): Promise<string | undefined> {
  if (!runId || !isTracingEnabled()) {
    return undefined;
  }
  const client = new Client();
  const projectName = process.env.LANGCHAIN_PROJECT || 'eureka-agents';
  // LangSmith puede tardar unos instantes en indexar el run recién creado.
  for (let intento = 0; intento < 3; intento += 1) {
    try {
      return await client.getRunUrl({ runId, projectOpts: { projectName } });
    } catch {
      if (intento < 2) {
        await new Promise((r) => setTimeout(r, 1200));
      }
    }
  }
  return undefined;
}

function ingresarPropuestaManual() {
  console.log('\nIngrese los datos de la propuesta (JSON):');
  console.log('Formato:');
  console.log(`{
  "agente": "finanzas|logistica|compras|ventas",
  "tipo": "propuesta|alerta|reporte",
  "resumen": "string",
  "datos_clave": {...},
  "riesgo": "bajo|medio|alto",
  "requiere_aprobacion_ceo": true|false
}`);

  rl.question('Propuesta JSON: ', (input) => {
    try {
      const propuesta: Propuesta = JSON.parse(input);
      void procesarPropuesta(propuesta);
    } catch (error: unknown) {
      if (error instanceof Error) {
        console.log('Error al parsear JSON:', error.message);
      } else {
        console.log('Error desconocido al parsear JSON');
      }
      mostrarMenu();
      rl.prompt();
    }
  });
}

async function procesarPropuesta(propuesta: Propuesta, opciones: OpcionesDecision = {}) {
  console.log('\nProcesando propuesta...');
  const decision = await CEO.tomarDecision(propuesta, [], opciones);

  console.log('\n=== DECISIÓN EJECUTIVA ===');
  console.log(`Decisión: ${decision.decision}`);
  console.log(`Justificación: ${decision.justificacion}`);
  if (decision.condiciones && decision.condiciones.length > 0) {
    console.log(`Condiciones: ${decision.condiciones.join(', ')}`);
  }
  console.log(`Agentes notificados: ${decision.agentes_notificados.join(', ')}`);
  console.log(`Siguiente paso: ${decision.siguiente_paso}`);

  // Aportes de cada agente (reflejan los spans hijos del árbol de traza)
  if (decision.aportes_agentes && decision.aportes_agentes.length > 0) {
    console.log('\n--- Aportes de los agentes (spans) ---');
    for (const aporte of decision.aportes_agentes) {
      console.log(`[${aporte.agente}] ${JSON.stringify(aporte.resultado)}`);
    }
  }

  if (decision.aportes_gemini) {
    console.log('\n--- Aporte del agente Gemini (Python) ---');
    console.log(JSON.stringify(decision.aportes_gemini, null, 2));
  }

  const link = await linkTraza(decision.run_id);
  if (link) {
    console.log('\n🔗 Traza en LangSmith:');
    console.log(link);
  }

  mostrarMenu();
  rl.prompt();
}

function procesar_con_gemini() {
  console.log('\nEjemplo de propuesta de Ventas (con evaluación Gemini):');
  console.log(JSON.stringify(propuestaEjemplo(), null, 2));
  void procesarPropuesta(propuestaEjemplo(), { ejecutarGemini: true });
}

console.log('Bienvenido al Sistema de Orquestación de EUREKA');
mostrarMenu();
rl.prompt();

rl.on('line', (input) => {
  switch (input.trim()) {
    case '1':
      ingresarPropuestaManual();
      break;
    case '2':
      console.log('\nEjemplo de propuesta de Ventas:');
      console.log(JSON.stringify(propuestaEjemplo(), null, 2));
      void procesarPropuesta(propuestaEjemplo());
      break;
    case '3':
      console.log('Saliendo...');
      rl.close();
      break;
    case '4':
      procesar_con_gemini();
      break;
    default:
      console.log('Opción no válida');
      mostrarMenu();
      rl.prompt();
  }
});