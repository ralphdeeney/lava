import type { PageServerLoad } from './$types';
import { protectedData } from '$lib/server/api';
import type { Project, Service } from '$lib/models';
export const load: PageServerLoad = async (event) => {
  const path = `/projects/${event.params.project_id}/services/${event.params.service_id}`;
  const [project, service, deployments] = await Promise.all([
    protectedData<Project>(event, `/projects/${event.params.project_id}`),
    protectedData<Service>(event, path),
    protectedData<Deployment[]>(event, `${path}/deployments`),
  ]);
  return { project, service, deployments };
};

type Deployment = { id: string; source_commit_sha: string; status: string; environment_id: string; created_at: string; failure_message?: string | null };
