import { Propuesta } from '../types/agent';
import { contextoEureka } from '../config/company';
import { traceable } from 'langsmith/traceable';

export class AgenteFinanzas {
  static validarPropuesta = traceable(
    (propuesta: Propuesta): { valida: boolean; mensaje: string } => {
      return AgenteFinanzas._validarPropuesta(propuesta);
    },
    { name: 'finanzas', run_type: 'tool' }
  );

  private static _validarPropuesta(propuesta: Propuesta): { valida: boolean; mensaje: string } {
    const { datos_clave } = propuesta;

    // Validar margen bruto
    if (datos_clave.margen_bruto !== undefined && datos_clave.margen_bruto < contextoEureka.objetivo_trimestral.margen_bruto) {
      return {
        valida: false,
        mensaje: `Margen bruto ${datos_clave.margen_bruto}% es inferior al objetivo trimestral de ${contextoEureka.objetivo_trimestral.margen_bruto}%`
      };
    }

    // Validar caja mínima
    if (datos_clave.caja_proyectada !== undefined && datos_clave.caja_proyectada < contextoEureka.restricciones.caja_minima) {
      return {
        valida: false,
        mensaje: `Caja proyectada $${datos_clave.caja_proyectada} es inferior a la mínima de $${contextoEureka.restricciones.caja_minima}`
      };
    }

    // Validar límite de deuda
    if (datos_clave.deuda_propuesta !== undefined) {
      const deuda_actual = datos_clave.deuda_actual || 0;
      if (deuda_actual + datos_clave.deuda_propuesta > contextoEureka.restricciones.limite_deuda) {
        return {
          valida: false,
          mensaje: `Deuda propuesta $${datos_clave.deuda_propuesta} supera el límite de $${contextoEureka.restricciones.limite_deuda}`
        };
      }
    }

    return { valida: true, mensaje: 'Propuesta válida desde la perspectiva financiera' };
  }

  static calcularImpactoCaja = traceable(
    (propuesta: Propuesta, caja_actual: number): number => {
      return AgenteFinanzas._calcularImpactoCaja(propuesta, caja_actual);
    },
    { name: 'finanzas_calcular_impacto_caja', run_type: 'tool' }
  );

  private static _calcularImpactoCaja(propuesta: Propuesta, caja_actual: number): number {
    const { datos_clave } = propuesta;
    let impacto = 0;

    if (datos_clave.ingreso_estimado) {
      impacto += datos_clave.ingreso_estimado;
    }

    if (datos_clave.egreso_estimado) {
      impacto -= datos_clave.egreso_estimado;
    }

    return caja_actual + impacto;
  }
}