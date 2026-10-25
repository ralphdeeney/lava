import type { PageServerLoad } from './$types';
import type { Invitation, Project, ProjectMembership } from '$lib/models';
import { protectedData } from '$lib/server/api';

export const load: PageServerLoad = async (event) => {
  await event.parent();
  const base = `/projects/${event.params.project_id}`;
  const project = await protectedData<Project>(event, base);
  const canManage = project.my_role === 'owner' || project.my_role === 'admin';
  const [members, invitations] = await Promise.all([
    protectedData<ProjectMembership[]>(event, `${base}/members`),
    canManage ? protectedData<Invitation[]>(event, `${base}/invitations`) : Promise.resolve([])
  ]);
  return { project, members, invitations };
};
