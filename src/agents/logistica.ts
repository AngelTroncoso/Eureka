import { Propuesta } from '../types/agent';
import { traceable } from 'langsmith/traceable';

export class AgenteLogistica {
  static validarPropuesta = traceable(
    (propuesta: Propuesta): { valida: boolean; mensaje: string } => {
      return AgenteLogistica._validarPropuesta(propuesta);
    },
    { name: 'logistica', run_type: 'tool' }
  );

  private static _validarPropuesta(propuesta: Propuesta): { valida: boolean; mensaje: string } {
    const { datos_clave } = propuesta;

    // Validar capacidad de almacenamiento
    if (datos_clave.stock_solicitado !== undefined) {
      const capacidad_actual = datos_clave.capacidad_actual || 0;
      const capacidad_maxima = datos_clave.capacidad_maxima || capacidad_actual;

      if (capacidad_actual + datos_clave.stock_solicitado > capacidad_maxima) {
        return {
          valida: false,
          mensaje: `Stock solicitado ${datos_clave.stock_solicitado} supera la capacidad máxima de ${capacidad_maxima}`
        };
      }
    }

    // Validar plazos de entrega
    if (datos_clave.plazo_entrega !== undefined) {
      const plazo_maximo = datos_clave.plazo_maximo || 30; // días por defecto

      if (datos_clave.plazo_entrega > plazo_maximo) {
        return {
          valida: false,
          mensaje: `Plazo de entrega ${datos_clave.plazo_entrega} días supera el máximo de ${plazo_maximo} días`
        };
      }
    }

    return { valida: true, mensaje: 'Propuesta válida desde la perspectiva logística' };
  }

  static calcularCapacidadRestante = traceable(
    (propuesta: Propuesta, capacidad_actual: number): number => {
      return AgenteLogistica._calcularCapacidadRestante(propuesta, capacidad_actual);
    },
    { name: 'logistica_calcular_capacidad_restante', run_type: 'tool' }
  );

  private static _calcularCapacidadRestante(propuesta: Propuesta, capacidad_actual: number): number {
    const { datos_clave } = propuesta;
    const stock_solicitado = datos_clave.stock_solicitado || 0;
    return capacidad_actual - stock_solicitado;
  }
}