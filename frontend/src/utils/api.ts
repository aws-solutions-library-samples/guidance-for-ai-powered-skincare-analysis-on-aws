import type { AnalysisUpdate, CompiledRoutine, IngredientPreferences, IngredientLookupResult } from '../types';
import { getIdToken } from './auth';
import { decodeJson, object, parseIngredients, parsePlan, parseProducts, parseRoutine, parseSkinProfile, recommendationOutcome } from './analysisData';
import { AnalysisError, httpError, serverError } from './analysisErrors';

function ensureSuccess(value: Record<string, unknown>) {
  if (typeof value.status !== 'string' || value.status.toLowerCase() !== 'completed') {
    throw new Error('Analysis could not complete. Please try again.');
  }
}

export class ApiService {
  constructor(private baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  /** Decode the graph stream into typed progress updates and one final routine. */
  async startAnalysis(
    images: string[],
    jobId: string,
    onUpdate: (update: AnalysisUpdate) => void,
    signal?: AbortSignal,
    preferences?: IngredientPreferences,
  ): Promise<CompiledRoutine> {
    try {
      return await this.readAnalysis(images, jobId, onUpdate, signal, preferences);
    } catch (error) {
      signal?.throwIfAborted();
      if (error instanceof AnalysisError) throw error;
      throw new AnalysisError('INVALID_RESPONSE', jobId);
    }
  }

  private async readAnalysis(
    images: string[], jobId: string, onUpdate: (update: AnalysisUpdate) => void, signal?: AbortSignal,
    preferences?: IngredientPreferences,
  ): Promise<CompiledRoutine> {
    let idToken: string | null;
    try {
      idToken = await getIdToken();
    } catch {
      signal?.throwIfAborted();
      throw new AnalysisError('AUTH_REQUIRED', jobId);
    }
    signal?.throwIfAborted();
    if (!idToken) throw new AnalysisError('AUTH_REQUIRED', jobId);

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${idToken}` },
        body: JSON.stringify({ job_id: jobId, images, ...(preferences !== undefined ? { api_version: 2, preferences } : {}) }),
        signal,
      });
    } catch {
      signal?.throwIfAborted();
      throw new AnalysisError('NETWORK_ERROR', jobId);
    }
    if (!response.ok) {
      // Only these documented proxy codes refine HTTP 429; arbitrary server
      // messages and unrelated provider JSON remain hidden.
      if ([400, 429].includes(response.status) && response.headers?.get('content-type')?.includes('application/json')) {
        const body = await response.json().catch(() => null);
        if (body && ['USER_RATE_LIMITED', 'ANALYSIS_IN_PROGRESS', 'INVALID_PREFERENCES'].includes(body.code)) {
          throw serverError(body, jobId);
        }
      }
      throw httpError(response.status, jobId);
    }
    if (!response.body) throw new Error('No analysis stream received.');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let dataLines: string[] = [];
    let routine: CompiledRoutine | undefined;
    let complete = false;

    const handleEvent = (value: unknown) => {
      signal?.throwIfAborted();
      const event = object(value);
      if (event.type === 'error') {
        throw serverError(event, jobId);
      }
      if (event.type === 'multiagent_result') {
        ensureSuccess(object(event.result));
        // Phase 1 also emits a graph result. Only the compiled routine is terminal.
        if (routine) complete = true;
        return;
      }
      if (event.type !== 'multiagent_node_start' && event.type !== 'multiagent_node_stop') return;
      if (typeof event.node_id !== 'string') throw new Error('Analysis event is missing its node.');
      const node = event.node_id;
      if (event.type === 'multiagent_node_start') {
        if (node === 'skin_analysis') onUpdate({ type: 'progress', step: 'skin_analysis', message: 'Analyzing your photos...' });
        else if (node === 'step_analysis') onUpdate({ type: 'progress', step: 'routine_planning', message: 'Planning your routine...' });
        else if (node.startsWith('ingredients_')) {
          const stepName = node.slice('ingredients_'.length);
          onUpdate({ type: 'progress', step: 'ingredients', stepName, message: `Selecting ingredients for ${stepName}...` });
        } else if (node.startsWith('products_')) {
          const stepName = node.slice('products_'.length);
          onUpdate({ type: 'progress', step: 'products', stepName, message: `Finding products for ${stepName}...` });
        }
        return;
      }
      const nodeResult = object(event.node_result);
      ensureSuccess(nodeResult);
      const result = object(nodeResult.result);
      const output = result.structured_output;
      if (node === 'skin_analysis') onUpdate({ type: 'skin_profile', profile: parseSkinProfile(output) });
      else if (node === 'step_analysis') onUpdate({ type: 'plan', steps: parsePlan(output) });
      else if (node.startsWith('ingredients_')) {
        const data = object(output);
        const stepName = node.slice('ingredients_'.length);
        if (data.step_name !== stepName) throw new Error('Analysis returned ingredients for the wrong step.');
        onUpdate({ type: 'ingredients', stepName, ingredients: parseIngredients(data.key_ingredients), analysisNotes: typeof data.analysis_notes === 'string' ? data.analysis_notes : '' });
      } else if (node.startsWith('products_')) {
        const data = object(output);
        const stepName = node.slice('products_'.length);
        if (data.step_name !== stepName) throw new Error('Analysis returned products for the wrong step.');
        const products = parseProducts(data.top_recommendations, preferences !== undefined);
        const outcome = data.status !== undefined ? recommendationOutcome(data.status, data.reason, products) : undefined;
        onUpdate({ type: 'products', stepName, products, ...(outcome ? { recommendationStatus: outcome.recommendation_status } : {}) });
      } else if (node === 'compile') {
        const compiled = object(object(result.results).compile);
        ensureSuccess(compiled);
        const message = object(object(compiled.result).message);
        if (!Array.isArray(message.content)) throw new Error('Analysis did not return a routine.');
        const block = message.content.map(object).find(block => typeof block.text === 'string');
        routine = parseRoutine(block?.text);
      }
    };

    const flushEvent = () => {
      if (!dataLines.length) return;
      const data = dataLines.join('\n');
      dataLines = [];
      handleEvent(decodeJson(data));
    };
    const readLine = (line: string) => {
      line = line.replace(/\r$/, '');
      if (!line) flushEvent();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
      // SSE comments, id, retry and event fields do not change our JSON contract.
    };

    try {
      while (true) {
        signal?.throwIfAborted();
        const { done, value } = await reader.read().catch(() => {
          signal?.throwIfAborted();
          throw new AnalysisError('NETWORK_ERROR', jobId);
        });
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) readLine(line);
      }
      buffer += decoder.decode();
      if (buffer) readLine(buffer);
      flushEvent();
      signal?.throwIfAborted();
      if (!complete || !routine) throw new Error('Analysis stream ended before a complete routine was received. Please try again.');
      return routine;
    } finally {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  }

  async lookupIngredients(
    input: { category_id?: string; references?: ({ name: string } | { ingredient_id: string })[] },
    signal?: AbortSignal,
  ): Promise<IngredientLookupResult> {
    const token = await getIdToken().catch(() => null);
    signal?.throwIfAborted();
    if (!token) throw new AnalysisError('AUTH_REQUIRED', '');
    const response = await fetch(`${this.baseUrl}/ingredients/lookup`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(input), signal,
    });
    if (!response.ok) throw httpError(response.status, '');
    const result = object(await response.json());
    signal?.throwIfAborted();
    const strings = (value: unknown) => Array.isArray(value) && value.every(item => typeof item === 'string');
    if (typeof result.taxonomy_version !== 'string' || !strings(result.categories)
        || !strings(result.supported_markets) || !strings(result.supported_currencies)) throw new AnalysisError('INVALID_RESPONSE', '');
    const currencies = object(result.currency_minor_units);
    if (Object.entries(currencies).some(([currency, digits]) => !/^[A-Z]{3}$/.test(currency)
        || typeof digits !== 'number' || !Number.isInteger(digits) || digits < 0 || digits > 4)
        || (result.supported_currencies as string[]).some(currency => currencies[currency] === undefined)) {
      throw new AnalysisError('INVALID_RESPONSE', '');
    }
    if (result.ingredients !== undefined && (!Array.isArray(result.ingredients) || result.ingredients.length > 30
        || result.ingredients.some(value => {
          const item = object(value);
          return typeof item.ingredient_id !== 'string' || typeof item.display_name !== 'string';
        }))) throw new AnalysisError('INVALID_RESPONSE', '');
    if (input.references && (!Array.isArray(result.results) || result.results.length !== input.references.length
        || result.results.some(value => {
          const item = object(value);
          return !['resolved', 'unresolved', 'ambiguous'].includes(String(item.status))
            || (item.status === 'resolved' && (typeof item.ingredient_id !== 'string' || typeof item.display_name !== 'string'));
        }))) throw new AnalysisError('INVALID_RESPONSE', '');
    return result as unknown as IngredientLookupResult;
  }
}
