import type { PageServerLoad } from './$types';
import type { Project, Service } from '$lib/models';
import { protectedData } from '$lib/server/api';
export const load: PageServerLoad = async (event) => {
  await event.parent();
  const path = `/projects/${event.params.project_id}`;
  const [project, service] = await Promise.all([protectedData<Project>(event, path), protectedData<Service>(event, `${path}/services/${event.params.service_id}`)]);
  return { project, service };
};
