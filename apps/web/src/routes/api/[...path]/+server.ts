import type { RequestHandler } from './$types';
import { acceptSessionCookie, backend, privateHeaders, requireSameOrigin } from '$lib/server/api';

const uuid = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const collection = new RegExp(`^projects(?:/${uuid}/services)?$`);
const item = new RegExp(`^projects/${uuid}(?:/services/${uuid})?$`);

function problem(status: number): Response {
  return new Response(JSON.stringify({ error: { code: 'request_failed', message: 'Request could not be completed' } }), {
    status, headers: (() => { const headers = privateHeaders(); headers.set('Content-Type', 'application/json'); return headers; })()
  });
}

const handler: RequestHandler = async (event) => {
  const path = event.params.path ?? '';
  const method = event.request.method;
  const authMethods: Record<string, string> = { 'auth/login': 'POST', 'auth/session': 'GET', 'auth/logout': 'POST', 'auth/logout-all': 'POST' };
  const allowed = authMethods[path] === method || (collection.test(path) && ['GET', 'POST'].includes(method)) || (item.test(path) && ['GET', 'PATCH', 'DELETE'].includes(method));
  if (!allowed) return problem(404);
  if (method !== 'GET' && !requireSameOrigin(event)) return problem(403);
  for (const [name, value] of event.url.searchParams) {
    if (method !== 'GET' || !collection.test(path) || !['limit', 'offset'].includes(name) || !/^\d{1,8}$/.test(value)) return problem(400);
  }
  let body: Uint8Array | undefined;
  if (['POST', 'PATCH'].includes(method)) {
    const type = event.request.headers.get('content-type')?.split(';')[0].trim();
    if (type !== 'application/json') return problem(415);
    const reader = event.request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader) {
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        size += part.value.byteLength;
        if (size > 16_384) { await reader.cancel(); return problem(413); }
        chunks.push(part.value);
      }
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  }
  const response = await backend(event, `/${path}${event.url.search}`, {
    method, body: body === undefined ? undefined : new TextDecoder().decode(body), csrf: event.request.headers.get('x-csrf-token') ?? undefined,
    origin: method === 'GET' ? undefined : event.url.origin
  });
  if (response.status >= 300 && response.status < 400) return problem(502);
  try { acceptSessionCookie(event, response); } catch { return problem(502); }
  const headers = privateHeaders();
  headers.set('Content-Type', 'application/json');
  return new Response(response.body, { status: response.status, headers });
};

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const DELETE = handler;
