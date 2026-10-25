export interface SessionView {
  user: { id: string; name: string };
  expires_at: string;
  csrf_token: string;
}
export interface Project {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  lifecycle_status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
  my_role: ProjectRole;
}
export type ProjectRole = 'owner' | 'admin' | 'developer' | 'viewer';
export interface ProjectMembership {
  id: string;
  project_id: string;
  user_id: string;
  user_name: string;
  role: ProjectRole;
  status: 'active' | 'revoked';
  created_at: string;
  updated_at: string;
  revoked_at: string | null;
}
export interface Invitation {
  id: string;
  project_id: string;
  project_name?: string;
  invitee_id: string;
  invitee_name: string;
  role: ProjectRole;
  status: 'pending' | 'accepted' | 'declined' | 'revoked' | 'expired';
  expires_at: string;
}
export interface Environment {
  id: string;
  project_id: string;
  name: string;
  slug: string;
  description: string;
  lifecycle_status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
}
export interface Service {
  id: string;
  project_id: string;
  name: string;
  service_type: 'web' | 'api' | 'worker' | 'database';
  desired_state: 'stopped' | 'running' | 'archived';
  resources: { cpu: number; memory_mb: number };
  environment_id?: string | null;
  build_method?: 'railpack' | 'dockerfile' | 'image';
  start_command?: string;
  deployment_branch?: string;
  config_revision?: number;
  desired_replicas?: number;
  created_at: string;
  updated_at: string;
}
