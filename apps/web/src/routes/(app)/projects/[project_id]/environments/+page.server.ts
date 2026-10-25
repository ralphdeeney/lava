import type { PageServerLoad } from './$types';
import type { Environment, Project } from '$lib/models';
import { protectedData } from '$lib/server/api';
export const load: PageServerLoad = async (event) => {
  await event.parent();
  const base = `/projects/${event.params.project_id}`;
  const [project, environments] = await Promise.all([
    protectedData<Project>(event, base), protectedData<Environment[]>(event, `${base}/environments`)
  ]);
  return { project, environments };
};
