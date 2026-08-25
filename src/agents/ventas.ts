import { Propuesta } from '../types/agent';
import { contextoEureka } from '../config/company';
import { traceable } from 'langsmith/traceable';

export class AgenteVentas {
  static validarPropuesta = traceable(
    (propuesta: Propuesta): { valida: boolean; mensaje: string } => {
      return AgenteVentas._validarPropuesta(propuesta);
    },
    { name: 'ventas', run_type: 'tool' }
  );

  private static _validarPropuesta(propuesta: Propuesta): { valida: boolean; mensaje: string } {
    const { datos_clave } = propuesta;

    // Validar margen mínimo
    if (datos_clave.margen_bruto !== undefined && datos_clave.margen_bruto < 0) {
      return {
        valida: false,
        mensaje: `margen bruto negativo ${datos_clave.margen_bruto}% viola el valor no negociable de no vender bajo costo`
      };
    }

    // Validar crecimiento de ventas
    if (datos_clave.crecimiento_ventas !== undefined) {
      const crecimiento_minimo = contextoEureka.objetivo_trimestral.crecimiento_ventas * 0.8; // 80% del objetivo

      if (datos_clave.crecimiento_ventas < crecimiento_minimo) {
        return {
          valida: false,
          mensaje: `Crecimiento de ventas ${datos_clave.crecimiento_ventas}% es inferior al 80% del objetivo trimestral`
        };
      }
    }

    return { valida: true, mensaje: 'Propuesta válida desde la perspectiva de ventas' };
  }

  static calcularImpactoVentas = traceable(
    (propuesta: Propuesta): number => {
      return AgenteVentas._calcularImpactoVentas(propuesta);
    },
    { name: 'ventas_calcular_impacto_ventas', run_type: 'tool' }
  );

  private static _calcularImpactoVentas(propuesta: Propuesta): number {
    const { datos_clave } = propuesta;
    const ventas_actuales = datos_clave.ventas_actuales || 0;
    const crecimiento = datos_clave.crecimiento_ventas || 0;
    return ventas_actuales * (1 + crecimiento / 100);
  }
}