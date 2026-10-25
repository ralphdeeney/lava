import { fail, redirect } from '@sveltejs/kit';
import type { Actions, PageServerLoad } from './$types';
import { acceptSessionCookie, backend, privateHeaders, requireSameOrigin, session } from '$lib/server/api';
import { safeNext } from '$lib/navigation';

export const load: PageServerLoad = async (event) => {
  event.setHeaders(Object.fromEntries(privateHeaders()));
  if (await session(event)) redirect(303, safeNext(event.url.searchParams.get('next')));
  return {};
};

export const actions: Actions = {
  default: async (event) => {
    if (!requireSameOrigin(event)) return fail(403, { message: 'This request is not allowed.' });
    const form = await event.request.formData();
    const username = form.get('username');
    const password = form.get('password');
    if (typeof username !== 'string' || typeof password !== 'string' || !username.trim() || !password || username.length > 100 || password.length > 1024) {
      return fail(400, { message: 'Enter your username and password.' });
    }
    const response = await backend(event, '/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }), origin: event.url.origin
    });
    if (!response.ok) {
      return fail(response.status === 429 ? 429 : 400, { message: response.status === 429 ? 'Too many login attempts. Please wait and try again.' : 'Unable to log in. Check your credentials and try again.' });
    }
    try { acceptSessionCookie(event, response); }
    catch { return fail(503, { message: 'The service is temporarily unavailable.' }); }
    redirect(303, safeNext(event.url.searchParams.get('next')));
  }
};
