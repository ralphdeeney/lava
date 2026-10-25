import type { PageServerLoad } from './$types';
import type { Invitation } from '$lib/models';
import { protectedData } from '$lib/server/api';
export const load: PageServerLoad = async (event) => {
  await event.parent();
  return { invitations: await protectedData<Invitation[]>(event, '/invitations') };
};
