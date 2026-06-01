import type {
  Assignment,
  AuditLogEntry,
  AuditLogStats,
  BulkSpawnReport,
  Classroom,
  ClusterStats,
  Deployment,
  DeploymentCredentialsResponse,
  DeploymentDetails,
  PaginatedResponse,
  PodInfo,
  PvcInfo,
  QuotaOverride,
  Quotas,
  ResourcePresets,
  RuntimeConfig,
  RuntimeConfigForm,
  StudentLabStatus,
  TeacherDashboard,
  Template,
  User,
  UserListParams,
} from "../types/api";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function redirectToLoginOnUnauthorized(path: string, status: number): void {
  if (status !== 401 || path === "/api/v1/auth/login" || path === "/api/v1/auth/logout") return;
  if (typeof window === "undefined" || window.location.pathname === "/login") return;
  window.location.href = "/login";
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text();

  if (!response.ok) {
    redirectToLoginOnUnauthorized(path, response.status);

    const detail =
      payload && typeof payload === "object"
        ? payload.detail || payload.message
        : typeof payload === "string" && payload.trim()
          ? payload
          : `HTTP ${response.status}`;
    throw new ApiError(
      Array.isArray(detail) ? detail.map((item) => item.msg || String(item)).join(", ") : String(detail),
      response.status,
    );
  }

  return payload as T;
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body: formData });
}

export function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

// ─── Auth ──────────────────────────────────────────────

export async function getCurrentUser(): Promise<User> {
  return apiFetch<User>("/api/v1/auth/me");
}

export async function getCheckRole(): Promise<{ role: string }> {
  return apiFetch("/api/v1/auth/check-role");
}

export async function login(username: string, password: string): Promise<{ user: User }> {
  return apiFetch<{ user: User }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function logout(): Promise<void> {
  try {
    await apiFetch("/api/v1/auth/logout", { method: "POST" });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return;
    throw error;
  }
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await apiFetch("/api/v1/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
}

export async function updateProfile(data: Partial<User>): Promise<User> {
  return apiFetch<User>("/api/v1/auth/me", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function getSsoStatus(): Promise<boolean> {
  try {
    const data = await apiFetch<{ sso_enabled: boolean }>("/api/v1/auth/sso/status");
    return Boolean(data.sso_enabled);
  } catch {
    return false;
  }
}

export async function registerUser(data: {
  username: string;
  email: string;
  full_name?: string;
  password: string;
  role?: string;
  is_active?: boolean;
}): Promise<User> {
  return apiFetch<User>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ role: "student", ...data }),
  });
}

// ─── Users (Admin) ─────────────────────────────────────

export async function getUsers(params?: UserListParams): Promise<User[]> {
  const qs = buildQuery(params as Record<string, string | number | boolean | undefined | null>);
  return apiFetch<User[]>(`/api/v1/auth/users${qs}`);
}

export async function getUser(userId: number): Promise<User> {
  return apiFetch<User>(`/api/v1/auth/users/${userId}`);
}

export async function updateUser(userId: number, data: Partial<User & { password: string }>): Promise<User> {
  return apiFetch<User>(`/api/v1/auth/users/${userId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteUser(userId: number): Promise<void> {
  await apiFetch(`/api/v1/auth/users/${userId}`, { method: "DELETE" });
}

export async function importUsersCsv(file: File): Promise<{
  created?: number;
  skipped?: number;
  errors?: string[];
  summary?: { created: number; skipped: number; errors: number };
  results?: Array<{ username?: string; email?: string; status: "created" | "skipped" | "error"; error?: string }>;
}> {
  const formData = new FormData();
  formData.append("file", file);
  return apiUpload("/api/v1/auth/users/import", formData);
}

// ─── Quota Overrides (Admin) ───────────────────────────

export async function getQuotaOverride(userId: number): Promise<QuotaOverride | null> {
  return apiFetch<QuotaOverride | null>(`/api/v1/auth/users/${userId}/quota-override`);
}

export async function setQuotaOverride(userId: number, override: QuotaOverride): Promise<void> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(override)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  await apiFetch(`/api/v1/auth/users/${userId}/quota-override?${params.toString()}`, { method: "PUT" });
}

export async function deleteQuotaOverride(userId: number): Promise<void> {
  await apiFetch(`/api/v1/auth/users/${userId}/quota-override`, { method: "DELETE" });
}

// ─── Deployments ───────────────────────────────────────

export interface CreateDeploymentInput {
  name: string;
  image: string;
  replicas: number;
  create_service: boolean;
  service_port: number;
  service_target_port: number;
  service_type: string;
  deployment_type: string;
  cpu_request: string;
  cpu_limit: string;
  memory_request: string;
  memory_limit: string;
  existing_pvc_name?: string;
}

export async function getDeployments(): Promise<Deployment[]> {
  const data = await apiFetch<{ deployments: Deployment[] }>("/api/v1/k8s/deployments/labondemand");
  return data.deployments || [];
}

export async function getAllDeployments(status?: string): Promise<Deployment[]> {
  const params = status ? `?status=${encodeURIComponent(status)}` : "";
  const data = await apiFetch<{ deployments: Deployment[] }>(`/api/v1/k8s/deployments/all${params}`);
  return data.deployments || [];
}

export async function getDeploymentDetails(namespace: string, name: string): Promise<DeploymentDetails> {
  return apiFetch<DeploymentDetails>(
    `/api/v1/k8s/deployments/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/details`,
  );
}

export async function getDeploymentCredentials(
  namespace: string,
  name: string,
): Promise<DeploymentCredentialsResponse> {
  return apiFetch(
    `/api/v1/k8s/deployments/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/credentials`,
  );
}

export async function createDeployment(input: CreateDeploymentInput): Promise<{ namespace?: string; message?: string; deployment_type?: string }> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(input)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return apiFetch(`/api/v1/k8s/deployments?${params.toString()}`, { method: "POST" });
}

export async function deleteDeployment(
  namespace: string,
  name: string,
  options?: { deleteService?: boolean; deletePersistent?: boolean },
): Promise<void> {
  const params = new URLSearchParams();
  if (options?.deleteService !== false) params.set("delete_service", "true");
  if (options?.deletePersistent) params.set("delete_persistent", "true");
  const qs = params.toString();
  await apiFetch(
    `/api/v1/k8s/deployments/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}${qs ? `?${qs}` : ""}`,
    { method: "DELETE" },
  );
}

export async function setDeploymentLifecycle(
  namespace: string,
  name: string,
  action: "pause" | "resume",
): Promise<void> {
  await apiFetch(`/api/v1/k8s/deployments/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}/${action}`, {
    method: "POST",
  });
}

// ─── PVCs ───────────────────────────────────────────────

export async function getPvcs(): Promise<PvcInfo[]> {
  const data = await apiFetch<{ items: PvcInfo[] }>("/api/v1/k8s/pvcs");
  return data.items || [];
}

export async function getAllPvcs(): Promise<PvcInfo[]> {
  const data = await apiFetch<{ items: PvcInfo[] }>("/api/v1/k8s/pvcs/all");
  return data.items || [];
}

export async function deletePvc(name: string, force = false): Promise<void> {
  await apiFetch(`/api/v1/k8s/pvcs/${encodeURIComponent(name)}${force ? "?force=true" : ""}`, { method: "DELETE" });
}

// ─── Templates ──────────────────────────────────────────

export async function getTemplates(): Promise<Template[]> {
  const data = await apiFetch<{ templates: Template[] }>("/api/v1/k8s/templates");
  return data.templates || [];
}

export async function getAllTemplates(): Promise<Template[]> {
  const data = await apiFetch<{ templates?: Template[] } | Template[]>("/api/v1/k8s/templates/all");
  return Array.isArray(data) ? data : data.templates || [];
}

export async function getResourcePresets(): Promise<ResourcePresets> {
  return apiFetch<ResourcePresets>("/api/v1/k8s/resource-presets");
}

export async function createTemplate(data: Template): Promise<Template> {
  return apiFetch<Template>("/api/v1/k8s/templates", { method: "POST", body: JSON.stringify(data) });
}

export async function updateTemplate(id: string | number, data: Partial<Template>): Promise<Template> {
  return apiFetch<Template>(`/api/v1/k8s/templates/${id}`, { method: "PUT", body: JSON.stringify(data) });
}

export async function deleteTemplate(id: string | number): Promise<void> {
  await apiFetch(`/api/v1/k8s/templates/${id}`, { method: "DELETE" });
}

// ─── Runtime Configs ────────────────────────────────────

export async function getRuntimeConfigs(): Promise<RuntimeConfig[]> {
  const data = await apiFetch<{ runtime_configs?: RuntimeConfig[] } | RuntimeConfig[]>("/api/v1/k8s/runtime-configs");
  return Array.isArray(data) ? data : data.runtime_configs || [];
}

export async function createRuntimeConfig(data: RuntimeConfigForm): Promise<RuntimeConfig> {
  return apiFetch<RuntimeConfig>("/api/v1/k8s/runtime-configs", { method: "POST", body: JSON.stringify(data) });
}

export async function updateRuntimeConfig(
  id: number,
  data: Partial<RuntimeConfigForm>,
): Promise<RuntimeConfig> {
  return apiFetch<RuntimeConfig>(`/api/v1/k8s/runtime-configs/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteRuntimeConfig(id: number): Promise<void> {
  await apiFetch(`/api/v1/k8s/runtime-configs/${id}`, { method: "DELETE" });
}

// ─── Quotas ─────────────────────────────────────────────

export async function getQuotas(): Promise<Quotas> {
  return apiFetch<Quotas>("/api/v1/quotas/me");
}

// ─── Usage ──────────────────────────────────────────────

export async function getUsageMyApps(): Promise<Array<{ name: string; namespace: string; cpu_m: number; mem_mi: number; pods?: number; source?: string }>> {
  const data = await apiFetch<{
    usage?: Record<string, { cpu_m: number; memory_mi: number }>;
    items?: Array<{ name: string; namespace: string; cpu_m: number; mem_mi: number; pods?: number; source?: string }>;
  }>("/api/v1/k8s/usage/my-apps");
  if (data.items) return data.items;
  return Object.entries(data.usage || {}).map(([name, usage]) => ({
    name,
    namespace: "",
    cpu_m: usage.cpu_m,
    mem_mi: usage.memory_mi,
  }));
}

// ─── Cluster Stats ──────────────────────────────────────

export async function getClusterStats(): Promise<ClusterStats> {
  const data = await apiFetch<ClusterStats>("/api/v1/k8s/stats/cluster");
  const cluster = data.cluster || {};
  return {
    ...data,
    total_deployments: data.total_deployments ?? cluster.deployments,
    ready_deployments: data.ready_deployments ?? cluster.deployments_ready,
    total_lab_apps: data.total_lab_apps ?? cluster.lab_apps,
    total_pods: data.total_pods ?? cluster.pods,
    total_namespaces: data.total_namespaces ?? cluster.namespaces,
    nodes: (data.nodes || []).map((node) => ({
      ...node,
      roles: Array.isArray(node.roles) ? node.roles.join(", ") : node.roles,
      cpu_usage_m: node.cpu_usage_m ?? node.cpu?.usage_m,
      cpu_allocatable_m: node.cpu_allocatable_m ?? node.cpu?.allocatable_m,
      mem_usage_mi: node.mem_usage_mi ?? node.memory?.usage_mi,
      mem_allocatable_mi: node.mem_allocatable_mi ?? node.memory?.allocatable_mi,
    })),
  };
}

export async function pingK8s(): Promise<boolean> {
  try {
    await apiFetch("/api/v1/k8s/ping");
    return true;
  } catch {
    return false;
  }
}

// ─── Admin K8s ──────────────────────────────────────────

export async function getNamespaces(): Promise<Array<{ name: string; status?: string }>> {
  const data = await apiFetch<{ namespaces: Array<string | { name: string; status?: string }> }>("/api/v1/k8s/namespaces");
  return (data.namespaces || []).map((item) => (typeof item === "string" ? { name: item } : item));
}

export async function getPods(namespace?: string): Promise<PodInfo[]> {
  const path = namespace ? `/api/v1/k8s/pods/${encodeURIComponent(namespace)}` : "/api/v1/k8s/pods";
  const data = await apiFetch<{ pods: PodInfo[] }>(path);
  return data.pods || [];
}

export async function getAllPods(): Promise<PodInfo[]> {
  return getPods();
}

export async function deletePod(namespace: string, name: string): Promise<void> {
  await apiFetch(`/api/v1/k8s/pods/${encodeURIComponent(namespace)}/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
}

export async function getAllK8sDeployments(): Promise<Deployment[]> {
  const data = await apiFetch<{ deployments: Deployment[] }>("/api/v1/k8s/deployments");
  return data.deployments || [];
}

// ─── Audit Logs ─────────────────────────────────────────

export async function getAuditLogStats(): Promise<AuditLogStats> {
  const data = await apiFetch<AuditLogStats>("/api/v1/audit-logs/stats");
  const last7 = data.last_7_days || (Array.isArray(data.activity_7d)
    ? Object.fromEntries(data.activity_7d.map((item) => [item.date, item.count]))
    : undefined);
  return {
    ...data,
    by_event: data.by_event || Object.fromEntries((data.top_events || []).map((item) => [item.event, item.count])),
    last_7_days: last7,
  };
}

export async function getAuditLogs(params: {
  page?: number;
  page_size?: number;
  event?: string;
  category?: string;
  username?: string;
  level?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
}): Promise<{ items?: AuditLogEntry[]; entries?: AuditLogEntry[]; total?: number }> {
  const qs = buildQuery(params as Record<string, string | number | boolean | undefined | null>);
  const data = await apiFetch<{ items?: AuditLogEntry[]; entries?: AuditLogEntry[]; total?: number }>(`/api/v1/audit-logs${qs}`);
  return { ...data, items: data.items || data.entries || [] };
}

export async function exportAuditLogs(params: {
  event?: string;
  category?: string;
  username?: string;
  level?: string;
  date_from?: string;
  date_to?: string;
  search?: string;
}): Promise<AuditLogEntry[]> {
  const qs = buildQuery({ ...params, export: "json" } as Record<string, string | number | boolean | undefined | null>);
  return apiFetch<AuditLogEntry[]>(`/api/v1/audit-logs${qs}`);
}

// ─── Classrooms ─────────────────────────────────────────

export async function getClassrooms(): Promise<Classroom[]> {
  return apiFetch<Classroom[]>("/api/v1/classrooms");
}

export async function getClassroom(cid: number): Promise<Classroom> {
  return apiFetch<Classroom>(`/api/v1/classrooms/${cid}`);
}

export async function createClassroom(data: { name: string; description?: string }): Promise<Classroom> {
  return apiFetch<Classroom>("/api/v1/classrooms", { method: "POST", body: JSON.stringify(data) });
}

export async function updateClassroom(cid: number, data: Partial<Classroom>): Promise<Classroom> {
  return apiFetch<Classroom>(`/api/v1/classrooms/${cid}`, { method: "PUT", body: JSON.stringify(data) });
}

export async function deleteClassroom(cid: number): Promise<void> {
  await apiFetch(`/api/v1/classrooms/${cid}`, { method: "DELETE" });
}

export async function getClassroomStudents(cid: number): Promise<StudentLabStatus[]> {
  return apiFetch<StudentLabStatus[]>(`/api/v1/classrooms/${cid}/students`);
}

export async function enrollStudents(cid: number, userIds: number[]): Promise<void> {
  await apiFetch(`/api/v1/classrooms/${cid}/students`, {
    method: "POST",
    body: JSON.stringify({ user_ids: userIds }),
  });
}

export async function createAndEnrollStudent(
  cid: number,
  data: { username: string; email: string; full_name?: string; password: string },
): Promise<User> {
  const created = await apiFetch<{ user_id: number; username: string; email?: string | null }>(
    `/api/v1/classrooms/${cid}/students/create`,
    { method: "POST", body: JSON.stringify(data) },
  );
  return { id: created.user_id, username: created.username, email: created.email, role: "student" };
}

export async function unenrollStudent(cid: number, userId: number): Promise<void> {
  await apiFetch(`/api/v1/classrooms/${cid}/students/${userId}`, { method: "DELETE" });
}

export async function importStudentsCsv(cid: number, file: File): Promise<void> {
  const formData = new FormData();
  formData.append("file", file);
  await apiUpload(`/api/v1/classrooms/${cid}/students/import`, formData);
}

// ─── Assignments ────────────────────────────────────────

export async function getAssignments(cid: number): Promise<Assignment[]> {
  return apiFetch<Assignment[]>(`/api/v1/classrooms/${cid}/assignments`);
}

export async function createAssignment(
  cid: number,
  data: {
    title: string;
    instructions?: string;
    template_key?: string;
    cpu_preset?: string;
    ram_preset?: string;
    due_at?: string;
  },
): Promise<Assignment> {
  return apiFetch<Assignment>(`/api/v1/classrooms/${cid}/assignments`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateAssignment(
  cid: number,
  aid: number,
  data: Partial<Assignment>,
): Promise<Assignment> {
  return apiFetch<Assignment>(`/api/v1/classrooms/${cid}/assignments/${aid}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function deleteAssignment(cid: number, aid: number): Promise<void> {
  await apiFetch(`/api/v1/classrooms/${cid}/assignments/${aid}`, { method: "DELETE" });
}

export async function deployAllAssignments(cid: number, aid: number): Promise<BulkSpawnReport> {
  return apiFetch<BulkSpawnReport>(`/api/v1/classrooms/${cid}/assignments/${aid}/deploy-all`, {
    method: "POST",
  });
}

// ─── Teacher Dashboard ──────────────────────────────────

export async function getTeacherDashboard(): Promise<TeacherDashboard> {
  return apiFetch<TeacherDashboard>("/api/v1/teacher/dashboard");
}

export async function searchStudents(query: string): Promise<User[]> {
  const qs = buildQuery({ q: query });
  const raw = await apiFetch<Array<{ user_id: number; username: string; email?: string | null }>>(
    `/api/v1/teacher/users/search${qs}`,
  );
  return raw.map((r) => ({ id: r.user_id, username: r.username, email: r.email, role: "student" as const }));
}

export async function getClassroomLabStatus(cid: number): Promise<StudentLabStatus[]> {
  return apiFetch<StudentLabStatus[]>(`/api/v1/classrooms/${cid}/students`);
}
