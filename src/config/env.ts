import * as path from 'path';
import * as dotenv from 'dotenv';

/**
 * Carga las variables del archivo .env (GOOGLE_API_KEY, LANGCHAIN_*, etc.)
 * en process.env. Debe ejecutarse UNA sola vez al arrancar la aplicación
 * (CLI), ANTES de que cualquier traceable cree su primer run.
 */
export function cargarEnv(directorio?: string): void {
  const raiz = directorio || process.cwd();
  dotenv.config({ path: path.join(raiz, '.env') });
}

/**
 * Indica si el tracing de LangSmith está habilitado según el entorno.
 * LangSmith (JS) activa el trace si LANGCHAIN_TRACING_V2 o LANGSMITH_TRACING_V2 === 'true'.
 */
export function isTracingEnabled(): boolean {
  const v2 = process.env.LANGCHAIN_TRACING_V2 || process.env.LANGSMITH_TRACING_V2 || 'false';
  return v2.toLowerCase() === 'true';
}