import { execFile } from 'child_process';
import { promisify } from 'util';
import * as path from 'path';
import { Propuesta, DecisionEjecutiva, Agente, AporteAgente } from '../types/agent';
import { contextoEureka } from '../config/company';
import { AgenteFinanzas } from '../agents/finanzas';
import { AgenteLogistica } from '../agents/logistica';
import { AgenteCompras } from '../agents/compras';
import { AgenteVentas } from '../agents/ventas';
import { evaluarObservacionesVentas } from '../agents/ventas-observador';
import { traceable, getCurrentRunTree } from 'langsmith/traceable';

const execFileAsync = promisify(execFile);

export interface OpcionesDecision {
  /** Ejecutar el agente Python de Gemini como subproceso (span hijo bajo decidirCEO). */
  ejecutarGemini?: boolean;
  /** Ruta del intérprete Python (por defecto: venv del proyecto). */
  pythonBin?: string;
  /** Ruta del script puente Python. */
  puentePython?: string;
}

export class CEO {
  private static obtenerAgenteClase(agente: Agente): any {
    const agentes: Record<Agente, any> = {
      finanzas: AgenteFinanzas,
      logistica: AgenteLogistica,
      compras: AgenteCompras,
      ventas: AgenteVentas
    };
    return agentes[agente];
  }

  private static _runIdActual(): string | undefined {
    const runTree = getCurrentRunTree(true) as any;
    return runTree && runTree.id !== undefined ? String(runTree.id) : undefined;
  }

  private static obtenerValidacionPrincipal(
    agente: Agente,
    validaciones: {
      finanzas: { valida: boolean; mensaje: string };
      logistica: { valida: boolean; mensaje: string };
      compras: { valida: boolean; mensaje: string };
      ventas: { valida: boolean; mensaje: string };
    }
  ): { valida: boolean; mensaje: string } {
    switch (agente) {
      case 'finanzas': return validaciones.finanzas;
      case 'logistica': return validaciones.logistica;
      case 'compras': return validaciones.compras;
      case 'ventas': return validaciones.ventas;
    }
  }

  /**
   * Ejecuta el agente Python de Gemini como subproceso y lo une como span hijo
   * del run raíz 'decidirCEO' propagando el dotted order (langsmith-trace).
   */
  private static async _ejecutarAgenteGemini(
    propuesta: Propuesta,
    opciones: OpcionesDecision
  ): Promise<Record<string, any>> {
    const cwd = process.cwd();
    const pythonBin = path.resolve(cwd, opciones.pythonBin || 'managed-deep-agent-env', 'Scripts', 'python.exe');
    const puentePython = path.resolve(cwd, opciones.puentePython || 'eureka_agent_bridge.py');

    // Propagar el contexto de traza del run padre (decidirCEO) al subproceso
    const runTree = getCurrentRunTree(true) as any;
    const headers = runTree && typeof runTree.toHeaders === 'function' ? runTree.toHeaders() : {};
    const envGemini: Record<string, string> = {
      ...(process.env as Record<string, string>),
      LANGSMITH_DOTTED_ORDER: String(headers['langsmith-trace'] || ''),
      LANGSMITH_BAGGAGE: String(headers['baggage'] || ''),
      EUREKA_PROPUESTA_JSON: JSON.stringify(propuesta)
    };

    let stdout = '';
    let stderr = '';
    try {
      const res = await execFileAsync(pythonBin, [puentePython], {
        env: envGemini,
        cwd,
        maxBuffer: 1024 * 1024
      });
      stdout = res.stdout;
      stderr = res.stderr;
    } catch (error: unknown) {
      // execFile con exit code != 0: el error real está en err.stdout / err.stderr
      const err = error as { stdout?: string; stderr?: string };
      stdout = err.stdout || '';
      stderr = err.stderr || '';
    }

    if (stderr && stderr.trim()) {
      console.error('[gemini] stderr:', stderr.trim());
    }

    // Solo el JSON final del stdout es la respuesta; los prints previos no rompen el parseo
    const lineas = stdout.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    const ultimaJson = [...lineas].reverse().find((l) => l.startsWith('{'));

    if (!ultimaJson) {
      throw new Error(`El agente Python no devolvió JSON. stdout: ${stdout.slice(0, 500)}`);
    }

    const resultado = JSON.parse(ultimaJson) as Record<string, any>;
    if (resultado.ok === false) {
      throw new Error(`Agente Gemini falló: ${resultado.error || 'error desconocido'}`);
    }
    return resultado;
  }

  private static cruzarDatos(propuesta: Propuesta, otrasPropuestas: Propuesta[]): { conflicto: boolean; mensaje: string } {
    const { agente, datos_clave } = propuesta;

    // Lógica de cruce específica según el agente
    switch (agente) {
      case 'ventas':
        // Ventas vs Finanzas: margen bruto
        const finanzas = otrasPropuestas.find(p => p.agente === 'finanzas');
        if (finanzas && datos_clave.margen_bruto !== undefined) {
          const margenFinanzas = finanzas.datos_clave.margen_bruto_requerido;
          if (margenFinanzas && datos_clave.margen_bruto < margenFinanzas) {
            return {
              conflicto: true,
              mensaje: `Ventas propone margen ${datos_clave.margen_bruto}% pero Finanzas requiere ${margenFinanzas}%`
            };
          }
        }
        break;

      case 'compras':
        // Compras vs Logística: capacidad de almacenamiento
        const logistica = otrasPropuestas.find(p => p.agente === 'logistica');
        if (logistica && datos_clave.stock_solicitado !== undefined) {
          const capacidadMaxima = logistica.datos_clave.capacidad_maxima;
          if (capacidadMaxima && datos_clave.stock_solicitado > capacidadMaxima) {
            return {
              conflicto: true,
              mensaje: `Compras solicita stock ${datos_clave.stock_solicitado} pero Logística solo puede manejar ${capacidadMaxima}`
            };
          }
        }
        break;

      case 'finanzas':
        // Finanzas vs Ventas: impacto en caja
        const ventas = otrasPropuestas.find(p => p.agente === 'ventas');
        if (ventas && datos_clave.caja_proyectada !== undefined) {
          const impactoVentas = AgenteVentas.calcularImpactoVentas(ventas);
          if (datos_clave.caja_proyectada < impactoVentas) {
            return {
              conflicto: true,
              mensaje: `Finanzas proyecta caja $${datos_clave.caja_proyectada} pero Ventas requiere $${impactoVentas}`
            };
          }
        }
        break;
    }

    return { conflicto: false, mensaje: 'Sin conflictos detectados' };
  }

  private static requiereEscalamiento(propuesta: Propuesta): boolean {
    const { datos_clave, riesgo } = propuesta;

    // Escalar por monto
    if (datos_clave.monto && datos_clave.monto > contextoEureka.umbral_escalamiento.monto) {
      return true;
    }

    // Escalar por riesgo legal
    if (riesgo === 'alto' && datos_clave.riesgo_legal) {
      return true;
    }

    return false;
  }

  private static async _tomarDecision(
    propuesta: Propuesta,
    otrasPropuestas: Propuesta[] = [],
    opciones: OpcionesDecision = {}
  ): Promise<DecisionEjecutiva> {
    const { agente, datos_clave, riesgo } = propuesta;

    // ─── REGLA ANTI-SILO (README): cruzar SIEMPRE con TODOS los agentes ───────
    // Se ejecutan los 5 agentes bajo el run padre; cada uno es un span hijo
    // (finanzas, logistica, compras, ventas, ventas-observador) con input/output.
    const [validacionFinanzas, validacionLogistica, validacionCompras, validacionVentas, observacionVentas] =
      await Promise.all([
        AgenteFinanzas.validarPropuesta(propuesta),
        AgenteLogistica.validarPropuesta(propuesta),
        AgenteCompras.validarPropuesta(propuesta),
        AgenteVentas.validarPropuesta(propuesta),
        evaluarObservacionesVentas(propuesta)
      ]);

    const validaciones = {
      finanzas: validacionFinanzas,
      logistica: validacionLogistica,
      compras: validacionCompras,
      ventas: validacionVentas
    };
    const validacion = this.obtenerValidacionPrincipal(agente, validaciones);

    const aportes_agentes: AporteAgente[] = [
      { agente: 'finanzas', tipo: 'validacion', resultado: validacionFinanzas },
      { agente: 'logistica', tipo: 'validacion', resultado: validacionLogistica },
      { agente: 'compras', tipo: 'validacion', resultado: validacionCompras },
      { agente: 'ventas', tipo: 'validacion', resultado: validacionVentas },
      { agente: 'ventas-observador', tipo: 'observacion', resultado: { ...observacionVentas } }
    ];

    // Cruce de datos con otras propuestas (regla: nunca decidir sin cruzar)
    const cruce = this.cruzarDatos(propuesta, otrasPropuestas);

    // Priorización: caja > legal > objetivos > operativo
    const decision: DecisionEjecutiva = {
      decision: 'aprobado',
      justificacion: '',
      agentes_notificados: [agente],
      siguiente_paso: 'Implementar propuesta',
      observaciones_ventas: observacionVentas,
      aportes_agentes,
      run_id: this._runIdActual()
    };

    // Notificar al ventas-observador si es propuesta de ventas
    if (agente === 'ventas' && observacionVentas) {
      decision.agentes_notificados.push('ventas-observador');
    }

    // Regla 1: Priorizar caja disponible (caja > legal > objetivos > operativo)
    if (datos_clave.caja_proyectada !== undefined) {
      const caja_actual = datos_clave.caja_actual || 100_000_000; // Valor por defecto
      const impacto = await AgenteFinanzas.calcularImpactoCaja(propuesta, caja_actual);

      if (impacto < contextoEureka.restricciones.caja_minima) {
        decision.decision = 'rechazado';
        decision.justificacion = `caja proyectada $${impacto} cae bajo el mínimo de $${contextoEureka.restricciones.caja_minima}. Priorizando liquidez sobre crecimiento.`;
        decision.siguiente_paso = 'Buscar alternativa con menor impacto en caja';
        return decision;
      }
    }

    // Regla 2: Validar propuesta con el agente correspondiente
    if (!validacion.valida) {
      decision.decision = 'rechazado';
      decision.justificacion = `Propuesta inválida: ${validacion.mensaje}`;
      decision.siguiente_paso = 'Reformular propuesta';
      return decision;
    }

    // Regla 3: Escalar si corresponde
    if (this.requiereEscalamiento(propuesta)) {
      decision.decision = 'escalado_a_humano';
      decision.justificacion = `Propuesta supera umbral de escalamiento: monto o riesgo legal`;
      decision.siguiente_paso = 'Revisión por humano';
      return decision;
    }

    // Regla 4: Manejar conflictos
    if (cruce.conflicto) {
      decision.decision = 'reformular';
      decision.justificacion = `Conflicto detectado: ${cruce.mensaje}`;
      decision.condiciones = ['Resolver conflicto con el agente afectado'];
      decision.siguiente_paso = 'Negociación entre agentes';
      return decision;
    }

    // ── REGLA 5 (veto cruzado): ningún aporte inválido se ignora ─────────────
    // La decisión NUNCA aprueba si algún agente marcó la propuesta como inválida:
    //   • Objeción del agente ORIGEN → rechazado directo (Regla 2).
    //   • Objeción de OTRO agente base (p. ej. Finanzas sobre una propuesta de
    //     Ventas) o alerta crítica del ventas-observador → desacuerdo entre
    //     agentes que el CEO autónomo no puede resolver solo → escala a humano.
    const objeciones = (Object.keys(validaciones) as Array<keyof typeof validaciones>)
      .filter((nombre) => !validaciones[nombre].valida)
      .map((nombre) => `${nombre}: ${validaciones[nombre].mensaje}`);

    const observadorCritico =
      observacionVentas &&
      (observacionVentas.severidad === 'critica' ||
        observacionVentas.recomendacionAlCeo === 'rechazar');

    if (objeciones.length > 0 || observadorCritico) {
      const detalle = [...objeciones];
      if (observadorCritico && observacionVentas) {
        detalle.push(
          `ventas-observador (${observacionVentas.severidad}/${observacionVentas.recomendacionAlCeo}): ${observacionVentas.evaluacion.trim()}`
        );
      }
      decision.decision = 'escalado_a_humano';
      decision.justificacion =
        'Aprobación automática bloqueada por objeciones entre agentes. ' +
        detalle.join(' | ');
      decision.condiciones = detalle;
      decision.siguiente_paso = 'Revisión humana: arbitrar las objeciones y re-someter';
      return decision;
    }

    // ── REGLA 6: la recomendación del ventas-observador nunca se ignora ──────
    if (observacionVentas && observacionVentas.recomendacionAlCeo !== 'aprobar') {
      if (observacionVentas.recomendacionAlCeo === 'escalar') {
        decision.decision = 'escalado_a_humano';
        decision.justificacion =
          `El ventas-observador recomienda escalar: ${observacionVentas.evaluacion.trim()}`;
        decision.siguiente_paso = 'Revisión humana';
        return decision;
      }
      if (observacionVentas.recomendacionAlCeo === 'solicitar_ajustes') {
        decision.decision = 'reformular';
        decision.justificacion =
          'El ventas-observador solicita ajustes antes de aprobar: ' +
          (observacionVentas.mejorasPropuestas || []).join(' ');
        decision.condiciones = [...(observacionVentas.mejorasPropuestas || [])];
        decision.siguiente_paso = 'Incorporar las mejoras propuestas y re-someter';
        return decision;
      }
    }

    // Si pasa todas las reglas, aprobar (los 5 aportes son favorables)
    decision.justificacion = `Propuesta validada por los 5 agentes sin objeciones. ${validacion.mensaje}. ${cruce.mensaje}.`;

    // ── Evaluación externa con Gemini (agente Python como subproceso) ──────
    if (opciones.ejecutarGemini) {
      try {
        const gemini = await this._ejecutarAgenteGemini(propuesta, opciones);
        decision.aportes_gemini = gemini.resultado !== undefined ? gemini.resultado : gemini;
        decision.agentes_notificados.push('gemini');
      } catch (error: unknown) {
        const msj = error instanceof Error ? error.message : String(error);
        decision.aportes_gemini = { error: msj };
        console.error(`[CEO] No se pudo ejecutar el agente Gemini: ${msj}`);
      }
    }

    return decision;
  }

  public static tomarDecision = traceable(
    async (propuesta: Propuesta, otrasPropuestas: Propuesta[] = [], opciones: OpcionesDecision = {}): Promise<DecisionEjecutiva> => {
      return CEO._tomarDecision(propuesta, otrasPropuestas, opciones);
    },
    { name: 'decidirCEO', run_type: 'chain' }
  );
}