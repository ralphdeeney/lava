import type { PageServerLoad } from './$types';
import type { Environment, Project, Service } from '$lib/models';
import { protectedData } from '$lib/server/api';
export const load: PageServerLoad = async (event) => {
  await event.parent();
  const base = `/projects/${event.params.project_id}`;
  const [project, environment, services] = await Promise.all([
    protectedData<Project>(event, base),
    protectedData<Environment>(event, `${base}/environments/${event.params.environment_id}`),
    protectedData<Service[]>(event, `${base}/services`)
  ]);
  return { project, environment, services: services.filter(service => service.environment_id === environment.id) };
};
