export type Agente = 'finanzas' | 'logistica' | 'compras' | 'ventas';
export type AgenteValidacion = 'finanzas' | 'logistica' | 'compras' | 'ventas';
export type AgenteObservador = 'ventas-observador';
export type TipoPropuesta = 'propuesta' | 'alerta' | 'reporte';
export type Riesgo = 'bajo' | 'medio' | 'alto';
export type Decision = 'aprobado' | 'rechazado' | 'reformular' | 'escalado_a_humano';

export interface Propuesta {
  agente: Agente;
  tipo: TipoPropuesta;
  resumen: string;
  datos_clave: Record<string, any>;
  riesgo: Riesgo;
  requiere_aprobacion_ceo: boolean;
}

export interface AporteAgente {
  agente: Agente | AgenteObservador | 'gemini';
  tipo: 'validacion' | 'observacion' | 'gemini';
  resultado: Record<string, any>;
}

export interface DecisionEjecutiva {
  decision: Decision;
  justificacion: string;
  condiciones?: string[];
  agentes_notificados: (Agente | AgenteObservador | 'gemini')[];
  siguiente_paso: string;
  observaciones_ventas?: ObservacionVentas;
  /** Resultado propio de cada agente involucrado en el proceso de decisión (spans del árbol de traza). */
  aportes_agentes?: AporteAgente[];
  /** Aporte del agente Python de Gemini cuando se solicita evaluación externa. */
  aportes_gemini?: Record<string, any>;
  /** ID del run raíz 'decidirCEO' en LangSmith (para construir el link de la traza). */
  run_id?: string;
}

export interface ObservacionVentas {
  agente: "ventas-observador";
  propuestaId: string;
  evaluacion: string;
  riesgos: string[];
  conflictosCon: ("finanzas" | "logistica" | "compras")[];
  mejorasPropuestas: string[];
  tradeOff: string;
  severidad: "critica" | "advertencia" | "sugerencia";
  recomendacionAlCeo: "aprobar" | "rechazar" | "escalar" | "solicitar_ajustes";
}

export interface ContextoEmpresa {
  objetivo_trimestral: {
    margen_bruto: number;
    crecimiento_ventas: number;
  };
  restricciones: {
    caja_minima: number;
    limite_deuda: number;
    max_porcentaje_caja_proyecto: number;
  };
  umbral_escalamiento: {
    monto: number;
    riesgos_legales: boolean;
    conflictos_irresolubles: boolean;
  };
  valores_no_negociables: string[];
}