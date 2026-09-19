/* Liten hjelper for å snakke med backend.
   - Legger på tidsavbrudd, så en tjeneste som henger ikke låser skjermen.
   - Gjør feil om til ApiError med en norsk melding som kan vises direkte. */

export class ApiError extends Error {
  constructor(message, { code = 'error', status = 0 } = {}) {
    super(message);
    this.code = code;
    this.status = status;
  }
  /** true hvis vi ikke fikk kontakt med backend i det hele tatt */
  get offline() { return this.status === 0; }
}

async function request(path, { method = 'GET', body, timeoutMs = 10000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });
  } catch (err) {
    const msg = err.name === 'AbortError'
      ? 'Serveren svarte ikke (tidsavbrudd)'
      : 'Ingen kontakt med serveren';
    throw new ApiError(msg, { code: 'offline', status: 0 });
  } finally {
    clearTimeout(timer);
  }

  let data = null;
  try { data = await response.json(); } catch { /* tomt eller ikke-JSON svar */ }

  if (!response.ok) {
    const err = data && data.error ? data.error : {};
    throw new ApiError(err.message || `Serveren svarte med feil (HTTP ${response.status})`, {
      code: err.code || 'http_error',
      status: response.status,
    });
  }
  return data;
}

export const api = {
  get: (path, opts) => request(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body: body ?? {} }),
  put: (path, body, opts) => request(path, { ...opts, method: 'PUT', body }),
};
