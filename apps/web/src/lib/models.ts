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
}
export interface Service {
  id: string;
  project_id: string;
  name: string;
  service_type: 'web' | 'api' | 'worker' | 'database';
  desired_state: 'stopped' | 'running' | 'archived';
  resources: { cpu: number; memory_mb: number };
  created_at: string;
  updated_at: string;
}
