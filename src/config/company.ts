import { ContextoEmpresa } from '../types/agent';

export const contextoEureka: ContextoEmpresa = {
  objetivo_trimestral: {
    margen_bruto: 25, // 25%
    crecimiento_ventas: 15 // 15% QoQ
  },
  restricciones: {
    caja_minima: 50_000_000, // $50M
    limite_deuda: 200_000_000, // $200M
    max_porcentaje_caja_proyecto: 30 // 30%
  },
  umbral_escalamiento: {
    monto: 100_000_000, // $100M
    riesgos_legales: true,
    conflictos_irresolubles: true
  },
  valores_no_negociables: [
    'No vender bajo costo',
    'Cumplir plazos legales',
    'No comprometer caja mínima',
    'No firmar contratos sin revisión de riesgo'
  ]
};