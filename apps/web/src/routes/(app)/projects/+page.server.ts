import type { PageServerLoad } from './$types';
import type { Project } from '$lib/models';
import { protectedData } from '$lib/server/api';
export const load: PageServerLoad = async (event) => {
  await event.parent();
  return { projects: await protectedData<Project[]>(event, '/projects') };
};
