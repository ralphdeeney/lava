import { env } from '$env/dynamic/private';
import { error, redirect, type RequestEvent } from '@sveltejs/kit';
import type { SessionView } from '$lib/models';
import { safeNext } from '$lib/navigation';

const sessionName = 'lava_session';

export function apiOrigin(): string {
  let parsed: URL;
  try { parsed = new URL(env.LAVA_API_ORIGIN ?? 'http://127.0.0.1:8000'); }
  catch { throw new Error('Invalid API origin configuration'); }
  const internalHTTP = parsed.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]', 'api'].includes(parsed.hostname);
  if ((!internalHTTP && parsed.protocol !== 'https:') || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error('Invalid API origin configuration');
  }
  return parsed.origin;
}

export function privateHeaders(): Headers {
  return new Headers({
    'Cache-Control': 'no-store, private',
    'Pragma': 'no-cache',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer'
  });
}

export function requireSameOrigin(event: RequestEvent): boolean {
  return event.request.headers.get('origin') === event.url.origin;
}

export async function backend(event: RequestEvent, path: string, init: { method?: string; body?: string; csrf?: string; origin?: string } = {}): Promise<Response> {
  const headers = new Headers({ 'Accept': 'application/json' });
  const cookie = event.cookies.get(sessionName);
  headers.set('Cookie', cookie ? `${sessionName}=${encodeURIComponent(cookie)}` : '');
  if (init.body !== undefined) headers.set('Content-Type', 'application/json');
  if (init.csrf) headers.set('X-CSRF-Token', init.csrf);
  if (init.origin) headers.set('Origin', init.origin);
  try {
    return await event.fetch(`${apiOrigin()}${path}`, {
      method: init.method ?? 'GET',
      headers,
      body: init.body,
      redirect: 'manual',
      signal: AbortSignal.timeout(10_000)
    });
  } catch {
    return new Response(JSON.stringify({ error: { code: 'unavailable', message: 'Service unavailable' } }), { status: 503 });
  }
}

export function acceptSessionCookie(event: RequestEvent, response: Response): void {
  for (const header of response.headers.getSetCookie()) {
    const segments = header.split(';').map((part) => part.trim());
    const [pair, ...attributes] = segments;
    const separator = pair.indexOf('=');
    if (separator < 0 || pair.slice(0, separator) !== sessionName) throw new Error('Invalid session response');
    const values = new Map<string, string>(attributes.map((attribute): [string, string] => {
      const index = attribute.indexOf('=');
      return index < 0 ? [attribute.toLowerCase(), ''] : [attribute.slice(0, index).toLowerCase(), attribute.slice(index + 1)];
    }));
    if (values.has('domain') || values.get('path') !== '/' || !values.has('httponly') || values.get('samesite')?.toLowerCase() !== 'lax') {
      throw new Error('Invalid session response');
    }
    const rawMaxAge = values.get('max-age');
    const maxAge = rawMaxAge === undefined ? undefined : Number(rawMaxAge);
    if (maxAge !== undefined && (!Number.isInteger(maxAge) || maxAge < 0 || maxAge > 31_536_000)) throw new Error('Invalid session response');
    const value = pair.slice(separator + 1);
    if (value && !/^[A-Za-z0-9_-]{20,200}$/.test(value)) throw new Error('Invalid session response');
    event.cookies.set(sessionName, value, { path: '/', httpOnly: true, sameSite: 'lax', secure: values.has('secure'), maxAge });
  }
}

export async function session(event: RequestEvent): Promise<SessionView | null> {
  if (!event.cookies.get(sessionName)) return null;
  const response = await backend(event, '/auth/session');
  if (response.status === 401) return null;
  if (!response.ok) error(503, 'The service is temporarily unavailable.');
  const value = await response.json() as SessionView;
  if (!value.user?.id || !value.user.name || !/^[a-f0-9]{64}$/.test(value.csrf_token) || !Number.isFinite(Date.parse(value.expires_at))) {
    error(503, 'The service is temporarily unavailable.');
  }
  return value;
}

export async function protectedData<T>(event: RequestEvent, path: string): Promise<T> {
  const response = await backend(event, path);
  if (response.status === 401) redirect(303, `/login?next=${encodeURIComponent(safeNext(event.url.pathname))}`);
  if (response.status === 404 || response.status === 403) error(404, 'This resource is not available.');
  if (!response.ok) error(503, 'The service is temporarily unavailable.');
  return response.json() as Promise<T>;
}
