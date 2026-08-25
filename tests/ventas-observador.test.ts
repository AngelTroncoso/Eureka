import { evaluarObservacionesVentas } from '../src/agents/ventas-observador';
import { Propuesta } from '../src/types/agent';

describe('Ventas Observador Agent', () => {
  test('Debería detectar margen bajo objetivo trimestral', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción con bajo margen',
      datos_clave: {
        margen_bruto: 20,
        crecimiento_ventas: 15,
        propuestaId: 'test-001'
      },
      riesgo: 'medio',
      requiere_aprobacion_ceo: true
    };

    const observacion = await evaluarObservacionesVentas(propuesta);

    expect(observacion.agente).toBe('ventas-observador');
    expect(observacion.riesgos).toContain('Margen bruto 20% por debajo del objetivo trimestral (25%)');
    expect(observacion.conflictosCon).toContain('finanzas');
    expect(observacion.severidad).toBe('advertencia');
    expect(observacion.recomendacionAlCeo).toBe('solicitar_ajustes');
    expect(observacion.mejorasPropuestas).toContain('Aumentar margen bruto en 5.0% mediante optimización de costos o ajuste de precios');
  });

  test('Debería detectar riesgo de venta bajo costo', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción con pérdida',
      datos_clave: {
        margen_bruto: -5,
        propuestaId: 'test-002'
      },
      riesgo: 'alto',
      requiere_aprobacion_ceo: true
    };

    const observacion = await evaluarObservacionesVentas(propuesta);

    expect(observacion.riesgos).toContain('Venta bajo costo viola valores no negociables de EUREKA');
    expect(observacion.conflictosCon).toContain('finanzas');
    expect(observacion.severidad).toBe('critica');
    expect(observacion.recomendacionAlCeo).toBe('rechazar');
  });

  test('Debería detectar conflicto con Finanzas por caja proyectada', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción con impacto en caja',
      datos_clave: {
        margen_bruto: 25,
        caja_proyectada: 45_000_000,
        propuestaId: 'test-003'
      },
      riesgo: 'medio',
      requiere_aprobacion_ceo: true
    };

    const observacion = await evaluarObservacionesVentas(propuesta);

    expect(observacion.riesgos).toContain('Caja proyectada $45000000 por debajo del mínimo ($50000000)');
    expect(observacion.conflictosCon).toContain('finanzas');
    expect(observacion.severidad).toBe('advertencia');
    expect(observacion.recomendacionAlCeo).toBe('solicitar_ajustes');
  });

  test('Debería aprobar propuesta válida con sugerencias', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción válida',
      datos_clave: {
        margen_bruto: 30,
        crecimiento_ventas: 20,
        propuestaId: 'test-004'
      },
      riesgo: 'bajo',
      requiere_aprobacion_ceo: true
    };

    const observacion = await evaluarObservacionesVentas(propuesta);

    expect(observacion.riesgos).toHaveLength(0);
    expect(observacion.conflictosCon).toHaveLength(0);
    expect(observacion.severidad).toBe('sugerencia');
    expect(observacion.recomendacionAlCeo).toBe('aprobar');
    expect(observacion.evaluacion).toContain('Margen bruto alineado con objetivos trimestrales');
    expect(observacion.evaluacion).toContain('Crecimiento de ventas alineado con objetivos trimestrales');
    expect(observacion.mejorasPropuestas).toHaveLength(1);
  });

  test('Debería generar ID de propuesta automáticamente', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción sin ID',
      datos_clave: {
        margen_bruto: 25
      },
      riesgo: 'bajo',
      requiere_aprobacion_ceo: true
    };

    const observacion = await evaluarObservacionesVentas(propuesta);

    expect(observacion.propuestaId).toMatch(/^prop-\d+/);
  });

  test('Debería incluir trade-off explícito', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción con trade-off',
      datos_clave: {
        margen_bruto: 30,
        crecimiento_ventas: 10,
        propuestaId: 'test-005'
      },
      riesgo: 'medio',
      requiere_aprobacion_ceo: true
    };

    const observacion = await evaluarObservacionesVentas(propuesta);

    expect(observacion.tradeOff).toContain('Alto margen vs bajo crecimiento');
  });
});