import { safeNext } from '$lib/navigation';

export class APIProblem extends Error {
  constructor(public status: number) {
    const messages: Record<number, string> = {
      401: 'Your session has expired. Please log in again.',
      403: 'This request is not allowed.',
      404: 'The requested resource is not available.',
      409: 'This change conflicts with the current resource state.',
      422: 'Check the form fields and try again.',
      429: 'Too many requests. Please wait and try again.'
    };
    super(messages[status] ?? 'The service is temporarily unavailable. Please try again.');
  }
}

export async function mutate<T>(path: string, method: 'POST' | 'PATCH' | 'DELETE', csrf: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
  } catch {
    throw new APIProblem(503);
  }
  if (response.status === 401 && typeof window !== 'undefined') {
    window.location.assign(`/login?next=${encodeURIComponent(safeNext(window.location.pathname))}`);
  }
  if (!response.ok) throw new APIProblem(response.status);
  return response.json() as Promise<T>;
}
