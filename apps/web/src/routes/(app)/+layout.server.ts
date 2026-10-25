import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';
import { privateHeaders, session } from '$lib/server/api';
import { safeNext } from '$lib/navigation';

export const load: LayoutServerLoad = async (event) => {
  event.setHeaders(Object.fromEntries(privateHeaders()));
  const next = safeNext(event.url.pathname);
  const active = await session(event);
  if (!active) redirect(303, `/login?next=${encodeURIComponent(next)}`);
  return { session: active };
};
