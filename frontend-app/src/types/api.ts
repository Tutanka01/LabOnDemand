export type Role = "admin" | "teacher" | "student";

export interface User {
  id: number;
  username: string;
  email?: string | null;
  full_name?: string | null;
  role: Role;
  is_active?: boolean;
  auth_provider?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface UserListParams {
  skip?: number;
  limit?: number;
  search?: string;
  role?: Role | "";
  auth_provider?: string;
}

export interface Template {
  id?: string | number;
  key?: string;
  name: string;
  description?: string | null;
  icon?: string | null;
  default_image?: string | null;
  default_port?: number | string | null;
  deployment_type?: string | null;
  default_service_type?: string | null;
  tags?: string[];
  active?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface RuntimeConfig {
  id: number;
  key: string;
  default_image: string;
  target_port: number;
  default_service_type: string;
  allowed_for_students: boolean;
  min_cpu_request: string;
  min_memory_request: string;
  min_cpu_limit: string;
  min_memory_limit: string;
  active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface RuntimeConfigForm {
  key: string;
  default_image: string;
  target_port: number;
  default_service_type: string;
  allowed_for_students: boolean;
  min_cpu_request: string;
  min_memory_request: string;
  min_cpu_limit: string;
  min_memory_limit: string;
  active: boolean;
}

export interface Quotas {
  role?: string;
  limits: {
    max_apps: number;
    max_pods?: number;
    max_requests_cpu_m: number;
    max_requests_mem_mi: number;
    max_storage_gi?: number;
  };
  usage: {
    apps_used: number;
    pods_used?: number;
    cpu_m_used: number;
    mem_mi_used: number;
    storage_gi_used?: number;
  };
  remaining?: {
    apps?: number;
    pods?: number;
    cpu_m?: number;
    mem_mi?: number;
    storage_gi?: number;
  };
}

export interface Lifecycle {
  state?: "running" | "paused" | "starting" | "mixed" | "unknown" | string;
  paused?: boolean;
  paused_at?: string | null;
  paused_by?: string | null;
}

export interface Deployment {
  name: string;
  namespace: string;
  type?: string;
  deployment_type?: string;
  ready_replicas?: number;
  replicas?: number;
  image?: string;
  lifecycle?: Lifecycle;
  lifecycle_summary?: Lifecycle;
  is_paused?: boolean;
  expires_at?: string | null;
  created_at?: string | null;
  labels?: Record<string, string>;
  owner_username?: string;
  cpu_requested?: number;
  mem_requested?: number;
}

export interface AccessUrl {
  url: string;
  label?: string;
  service?: string;
  node_port?: number;
}

export interface DeploymentDetails {
  deployment: {
    name: string;
    namespace: string;
    image?: string;
    replicas?: number;
    available_replicas?: number;
  };
  lifecycle?: Lifecycle;
  access_urls?: AccessUrl[];
  pods?: Array<{ name: string; status?: string; pod_ip?: string; node_name?: string }>;
  services?: Array<{
    name: string;
    type: string;
    cluster_ip?: string;
    ports?: Array<{ port: number; target_port: number | string; node_port?: number }>;
  }>;
  credentials?: Record<string, string>;
  novnc_endpoint?: string;
}

export interface PvcInfo {
  name: string;
  namespace?: string;
  phase?: string;
  storage?: string;
  access_modes?: string[];
  storage_class?: string | null;
  volume_name?: string | null;
  bound?: boolean;
  last_bound_app?: string;
  app_type?: string;
  created_at?: string;
  labels?: Record<string, string>;
}

export interface ResourcePreset {
  label: string;
  request: string;
  limit: string;
  value?: string;
}

export interface ResourcePresets {
  cpu: ResourcePreset[];
  memory: ResourcePreset[];
}

export interface PodInfo {
  name: string;
  namespace: string;
  status?: string;
  phase?: string;
  ip?: string | null;
  node_name?: string | null;
}

export interface ClusterStats {
  nodes?: ClusterNode[];
  cluster?: {
    nodes?: number;
    deployments?: number;
    deployments_ready?: number;
    lab_apps?: number;
    pods?: number;
    namespaces?: number;
  };
  total_deployments?: number;
  ready_deployments?: number;
  total_lab_apps?: number;
  total_pods?: number;
  total_namespaces?: number;
}

export interface ClusterNode {
  name?: string;
  roles?: string | string[];
  kubelet_version?: string;
  pods?: number;
  cpu_usage_m?: number;
  cpu_allocatable_m?: number;
  mem_usage_mi?: number;
  mem_allocatable_mi?: number;
  cpu?: { usage_m?: number; allocatable_m?: number; capacity_m?: number; usage_pct?: number };
  memory?: { usage_mi?: number; allocatable_mi?: number; capacity_mi?: number; usage_pct?: number };
}

export interface Classroom {
  id: number;
  name: string;
  description?: string | null;
  owner_id: number;
  archived: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  student_count?: number;
  active_assignment_count?: number;
}

export interface Enrollment {
  id: number;
  classroom_id: number;
  user_id: number;
  username?: string | null;
  email?: string | null;
  enrolled_at?: string | null;
  removed_at?: string | null;
}

export interface StudentLabStatus {
  user_id: number;
  username: string;
  email?: string | null;
  lab_name?: string | null;
  lab_status?: string | null;
  lab_expires_at?: string | null;
  last_seen_at?: string | null;
  enrolled_at?: string | null;
}

export interface Assignment {
  id: number;
  classroom_id: number;
  title: string;
  instructions?: string | null;
  template_key?: string | null;
  cpu_preset?: string | null;
  ram_preset?: string | null;
  due_at?: string | null;
  status?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface BulkSpawnResult {
  user_id: number;
  username: string;
  status: "ok" | "skipped" | "error";
  error?: string;
  deployment_name?: string;
}

export interface BulkSpawnReport {
  assignment_id: number;
  classroom_id: number;
  total: number;
  ok: number;
  skipped: number;
  errors: number;
  results: BulkSpawnResult[];
  summary?: {
    total: number;
    ok: number;
    skipped: number;
    errors: number;
  };
}

export interface TeacherDashboard {
  classroom_count?: number;
  classrooms?: Array<{
    id: number;
    name: string;
    description?: string | null;
    student_count: number;
    active_assignment_count: number;
    created_at?: string | null;
  }>;
  per_classroom?: Array<{
    classroom_id: number;
    classroom_name: string;
    student_count: number;
    active_labs: number;
    paused_labs: number;
  }>;
}

export interface AuditLogEntry {
  id?: number;
  timestamp?: string;
  event?: string;
  message?: string;
  event_label?: string;
  category?: string;
  level?: string;
  username?: string;
  detail?: string;
  source_ip?: string;
}

export interface AuditLogStats {
  total?: number;
  by_event?: Record<string, number>;
  by_level?: Record<string, number>;
  by_category?: Record<string, number>;
  last_7_days?: Record<string, number>;
  activity_7d?: Array<{ date: string; count: number }>;
  top_events?: Array<{ event: string; label?: string; count: number }>;
}

export interface QuotaOverride {
  max_apps?: number;
  max_cpu_m?: number;
  max_mem_mi?: number;
  max_storage_gi?: number;
  expires_at?: string | null;
}

export interface DeploymentCredential {
  service?: string;
  username?: string;
  password?: string;
  host?: string;
  port?: number;
  database?: string;
}

export interface DeploymentCredentialsResponse {
  type?: string;
  wordpress?: DeploymentCredential & { email?: string };
  database?: DeploymentCredential;
  secrets?: Record<string, string>;
  [service: string]: DeploymentCredential | Record<string, string> | string | undefined;
}

export interface UsageEntry {
  name: string;
  namespace: string;
  cpu_m?: number;
  memory_mi?: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
