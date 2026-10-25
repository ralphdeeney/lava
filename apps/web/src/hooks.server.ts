import type { Handle } from '@sveltejs/kit';

export const handle: Handle = async ({ event, resolve }) => {
  const response = await resolve(event);
  // Private page and BFF responses, including action failures and redirects, must not be cached.
  if (!event.url.pathname.startsWith('/_app/')) {
    response.headers.set('Cache-Control', 'no-store, private');
    response.headers.set('Pragma', 'no-cache');
    response.headers.set('X-Content-Type-Options', 'nosniff');
    response.headers.set('Referrer-Policy', 'no-referrer');
  }
  return response;
};
