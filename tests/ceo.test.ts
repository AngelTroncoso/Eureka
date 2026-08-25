import { CEO } from '../src/core/ceo';
import { Propuesta } from '../src/types/agent';

describe('CEO Decision Engine', () => {
  test('Debería aprobar propuesta válida', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción válida',
      datos_clave: {
        margen_bruto: 30,
        crecimiento_ventas: 20,
        caja_proyectada: 60_000_000,
        caja_actual: 70_000_000
      },
      riesgo: 'bajo',
      requiere_aprobacion_ceo: true
    };

    const decision = await CEO.tomarDecision(propuesta);
    expect(decision.decision).toBe('aprobado');
    expect(decision.agentes_notificados).toContain('ventas');
  });

  test('Debería rechazar propuesta con margen negativo', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción con pérdida',
      datos_clave: {
        margen_bruto: -5,
        caja_proyectada: 60_000_000
      },
      riesgo: 'alto',
      requiere_aprobacion_ceo: true
    };

    const decision = await CEO.tomarDecision(propuesta);
    expect(decision.decision).toBe('rechazado');
    expect(decision.justificacion).toContain('margen bruto negativo');
  });

  test('Debería escalar propuesta con monto alto', async () => {
    const propuesta: Propuesta = {
      agente: 'finanzas',
      tipo: 'propuesta',
      resumen: 'Inversión grande',
      datos_clave: {
        monto: 150_000_000,
        caja_proyectada: 80_000_000
      },
      riesgo: 'alto',
      requiere_aprobacion_ceo: true
    };

    const decision = await CEO.tomarDecision(propuesta);
    expect(decision.decision).toBe('escalado_a_humano');
    expect(decision.justificacion).toContain('umbral de escalamiento');
  });

  test('Debería rechazar propuesta que cae bajo caja mínima', async () => {
    const propuesta: Propuesta = {
      agente: 'finanzas',
      tipo: 'propuesta',
      resumen: 'Inversión riesgosa',
      datos_clave: {
        caja_proyectada: 40_000_000,
        caja_actual: 50_000_000,
        egreso_estimado: 20_000_000
      },
      riesgo: 'alto',
      requiere_aprobacion_ceo: true
    };

    const decision = await CEO.tomarDecision(propuesta);
    expect(decision.decision).toBe('rechazado');
    expect(decision.justificacion).toContain('caja proyectada');
    expect(decision.justificacion).toContain('Priorizando liquidez sobre crecimiento');
  });

  test('Debería detectar conflicto entre ventas y finanzas', async () => {
    const propuestaVentas: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción con bajo margen',
      datos_clave: {
        margen_bruto: 18,
        caja_proyectada: 60_000_000
      },
      riesgo: 'medio',
      requiere_aprobacion_ceo: true
    };

    const propuestaFinanzas: Propuesta = {
      agente: 'finanzas',
      tipo: 'propuesta',
      resumen: 'Requerimiento de margen',
      datos_clave: {
        margen_bruto_requerido: 25
      },
      riesgo: 'bajo',
      requiere_aprobacion_ceo: true
    };

    const decision = await CEO.tomarDecision(propuestaVentas, [propuestaFinanzas]);
    expect(decision.decision).toBe('reformular');
    expect(decision.justificacion).toContain('Conflicto detectado');
  });

  test('Debería incluir aportes de los 5 agentes en cada decisión', async () => {
    const propuesta: Propuesta = {
      agente: 'ventas',
      tipo: 'propuesta',
      resumen: 'Promoción válida',
      datos_clave: {
        margen_bruto: 30,
        crecimiento_ventas: 20,
        caja_proyectada: 60_000_000,
        caja_actual: 70_000_000
      },
      riesgo: 'bajo',
      requiere_aprobacion_ceo: true
    };

    const decision = await CEO.tomarDecision(propuesta);
    const agentes = (decision.aportes_agentes || []).map((a) => a.agente);
    expect(agentes).toContain('finanzas');
    expect(agentes).toContain('logistica');
    expect(agentes).toContain('compras');
    expect(agentes).toContain('ventas');
    expect(agentes).toContain('ventas-observador');
  });
});