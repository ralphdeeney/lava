import type { PageServerLoad } from './$types';
import type { Environment, Project } from '$lib/models';
import { error } from '@sveltejs/kit';
import { protectedData } from '$lib/server/api';
export const load: PageServerLoad = async (event) => {
  await event.parent();
  const base = `/projects/${event.params.project_id}`;
  const [project, environments] = await Promise.all([protectedData<Project>(event, base), protectedData<Environment[]>(event, `${base}/environments`)]);
  if (project.my_role === 'viewer' || project.lifecycle_status === 'archived') error(403, 'You cannot configure this project.');
  return { project, environments };
};
