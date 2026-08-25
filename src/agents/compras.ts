import { Propuesta } from '../types/agent';
import { traceable } from 'langsmith/traceable';

export class AgenteCompras {
  static validarPropuesta = traceable(
    (propuesta: Propuesta): { valida: boolean; mensaje: string } => {
      return AgenteCompras._validarPropuesta(propuesta);
    },
    { name: 'compras', run_type: 'tool' }
  );

  private static _validarPropuesta(propuesta: Propuesta): { valida: boolean; mensaje: string } {
    const { datos_clave } = propuesta;

    // Validar precio de compra
    if (datos_clave.precio_compra !== undefined && datos_clave.precio_mercado !== undefined) {
      const variacion_maxima = 0.15; // 15% de variación permitida

      if (datos_clave.precio_compra > datos_clave.precio_mercado * (1 + variacion_maxima)) {
        return {
          valida: false,
          mensaje: `Precio de compra $${datos_clave.precio_compra} supera el precio de mercado en más del 15%`
        };
      }
    }

    // Validar calidad del proveedor
    if (datos_clave.calidad_proveedor !== undefined && datos_clave.calidad_proveedor < 3) {
      return {
        valida: false,
        mensaje: `Calidad del proveedor ${datos_clave.calidad_proveedor}/5 es insuficiente (mínimo 3/5)`
      };
    }

    return { valida: true, mensaje: 'Propuesta válida desde la perspectiva de compras' };
  }

  static calcularAhorro = traceable(
    (propuesta: Propuesta): number => {
      return AgenteCompras._calcularAhorro(propuesta);
    },
    { name: 'compras_calcular_ahorro', run_type: 'tool' }
  );

  private static _calcularAhorro(propuesta: Propuesta): number {
    const { datos_clave } = propuesta;
    const precio_compra = datos_clave.precio_compra || 0;
    const precio_mercado = datos_clave.precio_mercado || precio_compra;
    return precio_mercado - precio_compra;
  }
}