import { fail, redirect, type RequestEvent } from '@sveltejs/kit';
import type { Actions } from './$types';
import { acceptSessionCookie, backend, requireSameOrigin, session } from '$lib/server/api';

async function logout(event: RequestEvent, all: boolean) {
  if (!requireSameOrigin(event)) return fail(403, { message: 'This request is not allowed.' });
  const current = await session(event);
  if (!current) { event.cookies.delete('lava_session', { path: '/' }); redirect(303, '/login'); }
  const response = await backend(event, all ? '/auth/logout-all' : '/auth/logout', {
    method: 'POST', body: '{}', csrf: current.csrf_token, origin: event.url.origin
  });
  if (response.status === 401) { event.cookies.delete('lava_session', { path: '/' }); redirect(303, '/login'); }
  if (!response.ok) return fail(503, { message: 'Unable to log out. Please try again.' });
  try { acceptSessionCookie(event, response); }
  catch { return fail(503, { message: 'Unable to log out. Please try again.' }); }
  redirect(303, '/login');
}

export const actions: Actions = {
  logout: (event) => logout(event, false),
  logoutAll: (event) => logout(event, true)
};
