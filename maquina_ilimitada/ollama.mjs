// Cliente mínimo de Ollama local (sin llaves). format=json, temperatura baja.
const URL_BASE = process.env.OLLAMA_URL || 'http://localhost:11434';

export async function generar(prompt, {modelo, semilla = 1, temperatura = 0.2, maxTokens = 1400, ctx = 4096, timeoutMs = 600000} = {}) {
  const t0 = Date.now();
  const r = await fetch(`${URL_BASE}/api/generate`, {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({model: modelo, prompt, stream: false, format: 'json', keep_alive: '6h', options: {temperature: temperatura, seed: semilla, num_ctx: ctx, num_predict: maxTokens}}),
    signal: AbortSignal.timeout(timeoutMs)
  });
  if (!r.ok) throw Error('Ollama HTTP ' + r.status);
  const d = await r.json();
  return {texto: d.response || '', segundos: (Date.now() - t0) / 1000, tokens_salida: d.eval_count || null, tokens_entrada: d.prompt_eval_count || null};
}

// Pide JSON; reintenta si es inválido. Devuelve {datos|null, intentos, json_validos, segundos, ...}
export async function pedirJSON(prompt, opts = {}, validar = x => x && typeof x === 'object', reintentos = 3, gen = generar) {
  let segundos = 0, jsonOk = 0, ultimo = null;
  for (let i = 0; i < reintentos; i++) {
    try {
      const r = await gen(prompt, {...opts, semilla: (opts.semilla || 1) + i, temperatura: i ? 0.3 : (opts.temperatura ?? 0.2)});
      segundos += r.segundos; ultimo = r;
      let d = null; try { d = JSON.parse(r.texto); } catch { /* JSON inválido */ }
      if (d !== null) jsonOk++;
      if (d !== null && validar(d)) return {datos: d, intentos: i + 1, json_validos: jsonOk, segundos, tokens_salida: r.tokens_salida};
    } catch (e) { ultimo = {error: e.message}; }
  }
  return {datos: null, intentos: reintentos, json_validos: jsonOk, segundos, error: ultimo?.error || 'JSON inválido o sin estructura'};
}
