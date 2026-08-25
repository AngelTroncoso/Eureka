import { Propuesta, ObservacionVentas, ContextoEmpresa } from '../types/agent';
import { contextoEureka } from '../config/company';
import { traceable } from 'langsmith/traceable';

export const evaluarObservacionesVentas = traceable(
  (propuesta: Propuesta, contexto: ContextoEmpresa = contextoEureka): ObservacionVentas => {
    return _evaluarObservacionesVentas(propuesta, contexto);
  },
  { name: 'ventas-observador', run_type: 'tool' }
);

function _evaluarObservacionesVentas(propuesta: Propuesta, contexto: ContextoEmpresa = contextoEureka): ObservacionVentas {
  const { datos_clave } = propuesta;
  const observacion: ObservacionVentas = {
    agente: "ventas-observador",
    propuestaId: propuesta.datos_clave.propuestaId || `prop-${Date.now()}`,
    evaluacion: "",
    riesgos: [],
    conflictosCon: [],
    mejorasPropuestas: [],
    tradeOff: "",
    severidad: "sugerencia",
    recomendacionAlCeo: "aprobar"
  };

  // 1. Evaluar alineación con objetivos trimestrales
  const margenBruto = datos_clave.margen_bruto !== undefined ? datos_clave.margen_bruto : null;
  const crecimientoVentas = datos_clave.crecimiento_ventas !== undefined ? datos_clave.crecimiento_ventas : null;

  if (margenBruto !== null) {
    if (margenBruto < contexto.objetivo_trimestral.margen_bruto) {
      observacion.riesgos.push(`Margen bruto ${margenBruto}% por debajo del objetivo trimestral (${contexto.objetivo_trimestral.margen_bruto}%)`);
      observacion.conflictosCon.push("finanzas");
      observacion.severidad = "advertencia";
    } else {
      observacion.evaluacion += "Margen bruto alineado con objetivos trimestrales. ";
    }
  }

  if (crecimientoVentas !== null) {
    if (crecimientoVentas < contexto.objetivo_trimestral.crecimiento_ventas) {
      observacion.riesgos.push(`Crecimiento de ventas ${crecimientoVentas}% por debajo del objetivo trimestral (${contexto.objetivo_trimestral.crecimiento_ventas}%)`);
      observacion.severidad = "advertencia";
    } else {
      observacion.evaluacion += "Crecimiento de ventas alineado con objetivos trimestrales. ";
    }
  }

  // 2. Detección de riesgo de venta bajo costo
  if (margenBruto !== null && margenBruto <= 0) {
    observacion.riesgos.push("Venta bajo costo viola valores no negociables de EUREKA");
    observacion.conflictosCon.push("finanzas");
    observacion.severidad = "critica";
    observacion.recomendacionAlCeo = "rechazar";
  }

  // 3. Detección de conflictos con otros agentes
  if (datos_clave.caja_proyectada !== undefined) {
    const cajaMinima = contexto.restricciones.caja_minima;
    if (datos_clave.caja_proyectada < cajaMinima) {
      observacion.riesgos.push(`Caja proyectada $${datos_clave.caja_proyectada} por debajo del mínimo ($${cajaMinima})`);
      observacion.conflictosCon.push("finanzas");
      observacion.severidad = "critica";
      observacion.recomendacionAlCeo = "solicitar_ajustes";
    }
  }

  // 4. Proponer mejoras concretas
  if (margenBruto !== null && margenBruto < contexto.objetivo_trimestral.margen_bruto) {
    const margenFaltante = contexto.objetivo_trimestral.margen_bruto - margenBruto;
    observacion.mejorasPropuestas.push(`Aumentar margen bruto en ${margenFaltante.toFixed(1)}% mediante optimización de costos o ajuste de precios`);
  }

  if (crecimientoVentas !== null && crecimientoVentas < contexto.objetivo_trimestral.crecimiento_ventas) {
    const crecimientoFaltante = contexto.objetivo_trimestral.crecimiento_ventas - crecimientoVentas;
    observacion.mejorasPropuestas.push(`Implementar estrategia de crecimiento para aumentar ventas en ${crecimientoFaltante.toFixed(1)}%`);
  }

  // Asegurar al menos una mejora propuesta
  if (observacion.mejorasPropuestas.length === 0) {
    observacion.mejorasPropuestas.push("Realizar análisis de mercado para identificar oportunidades de optimización");
  }

  // 5. Definir trade-off explícito
  if (margenBruto !== null && crecimientoVentas !== null) {
    if (margenBruto > contexto.objetivo_trimestral.margen_bruto && crecimientoVentas < contexto.objetivo_trimestral.crecimiento_ventas) {
      observacion.tradeOff = "Alto margen vs bajo crecimiento: priorizar margen a corto plazo puede limitar expansión de mercado";
    } else if (margenBruto < contexto.objetivo_trimestral.margen_bruto && crecimientoVentas > contexto.objetivo_trimestral.crecimiento_ventas) {
      observacion.tradeOff = "Bajo margen vs alto crecimiento: crecimiento acelerado puede comprometer rentabilidad";
    } else {
      observacion.tradeOff = "Equilibrio entre margen y crecimiento alineado con objetivos estratégicos";
    }
  } else {
    observacion.tradeOff = "Enfoque en mantener equilibrio entre objetivos comerciales y restricciones financieras";
  }

  // 6. Determinar severidad final
  if (observacion.riesgos.some(r => r.includes("viola valores no negociables"))) {
    observacion.severidad = "critica";
    observacion.recomendacionAlCeo = "rechazar";
  } else if (observacion.riesgos.length > 0) {
    observacion.severidad = "advertencia";
    if (observacion.recomendacionAlCeo === "aprobar") {
      observacion.recomendacionAlCeo = "solicitar_ajustes";
    }
  }

  // 7. Asegurar evaluación completa
  if (observacion.evaluacion === "") {
    observacion.evaluacion = "Propuesta evaluada desde perspectiva comercial con observaciones adjuntas.";
  }

  return observacion;
}