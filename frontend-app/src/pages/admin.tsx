import "../styles/main.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Boxes,
  Cpu,
  Download,
  Edit2,
  ExternalLink,
  FileJson,
  Package,
  PauseCircle,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  Sliders,
  Trash2,
  Upload,
  Users,
  Wrench,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AppShell, PageHeader } from "../components/AppShell";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  Pagination,
  SearchBox,
  StatusBadge,
  TabContent,
  TabList,
  TabTrigger,
  Tabs,
  ToastContainer,
  showToast,
} from "../components/ui";
import { UserDialog } from "../components/admin/UserDialog";
import { QuotaDialog } from "../components/admin/QuotaDialog";
import { CsvImportDialog } from "../components/admin/CsvImportDialog";
import { TemplateDialog } from "../components/admin/TemplateDialog";
import { RuntimeConfigDialog } from "../components/admin/RuntimeConfigDialog";
import { AuditLogViewer } from "../components/admin/AuditLogViewer";
import type { Deployment, RuntimeConfig, Template, User } from "../types/api";
import {
  deleteDeployment,
  deleteRuntimeConfig,
  deleteTemplate,
  deleteUser,
  getAllDeployments,
  getAllTemplates,
  getRuntimeConfigs,
  getSsoStatus,
  getUsers,
  setDeploymentLifecycle,
} from "../lib/api";
import { authProviderLabel, fullDate, roleLabel, shortDate, ttl } from "../lib/format";
import { QueryProvider } from "../lib/query";

function AdminPage() {
  const queryClient = useQueryClient();
  const initialTab = window.location.hash?.replace("#", "") || new URLSearchParams(window.location.search).get("tab") || "users";
  const [tab, setTab] = useState(initialTab);
  const [userFilter, setUserFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [authFilter, setAuthFilter] = useState("");
  const [userPage, setUserPage] = useState(1);
  const [userLimit, setUserLimit] = useState(25);
  const [showUserDialog, setShowUserDialog] = useState(false);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [quotaUser, setQuotaUser] = useState<User | null>(null);
  const [showCsvImport, setShowCsvImport] = useState(false);
  const [showTemplateDialog, setShowTemplateDialog] = useState(false);
  const [editTemplate, setEditTemplate] = useState<Template | null>(null);
  const [showRuntimeDialog, setShowRuntimeDialog] = useState(false);
  const [editRuntime, setEditRuntime] = useState<RuntimeConfig | null>(null);
  const [labFilter, setLabFilter] = useState("");
  const [labStatusFilter, setLabStatusFilter] = useState("");
  const [labTypeFilter, setLabTypeFilter] = useState("");

  const sso = useQuery({ queryKey: ["sso-status"], queryFn: getSsoStatus });

  const users = useQuery({
    queryKey: ["users", { search: userFilter, role: roleFilter, auth_provider: authFilter, userPage, userLimit }],
    queryFn: () =>
      getUsers({
        search: userFilter || undefined,
        role: (roleFilter as "admin" | "teacher" | "student") || undefined,
        auth_provider: authFilter || undefined,
        skip: (userPage - 1) * userLimit,
        limit: userLimit,
      }),
  });

  const templates = useQuery({ queryKey: ["templates-all"], queryFn: getAllTemplates });
  const runtimeConfigs = useQuery({ queryKey: ["runtime-configs"], queryFn: getRuntimeConfigs });
  const labFleet = useQuery({
    queryKey: ["deployments-all", labStatusFilter],
    queryFn: () => getAllDeployments(labStatusFilter || undefined),
  });

  const deleteUserMut = useMutation({
    mutationFn: (userId: number) => deleteUser(userId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["users"] }); showToast("Utilisateur supprime", "success"); },
  });

  const deleteTemplateMut = useMutation({
    mutationFn: (id: string | number) => deleteTemplate(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["templates-all"] }); showToast("Template supprime", "success"); },
  });

  const deleteRuntimeMut = useMutation({
    mutationFn: (id: number) => deleteRuntimeConfig(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["runtime-configs"] }); showToast("Runtime supprime", "success"); },
  });

  const deleteLabMut = useMutation({
    mutationFn: (d: Deployment) => deleteDeployment(d.namespace, d.name),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["deployments-all"] }); showToast("Lab supprime", "success"); },
  });

  const lifecycleMut = useMutation({
    mutationFn: ({ d, action }: { d: Deployment; action: "pause" | "resume" }) =>
      setDeploymentLifecycle(d.namespace, d.name, action),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["deployments-all"] }); showToast("Action executee", "success"); },
  });

  useEffect(() => {
    if (["users", "catalog", "runtimes", "labs", "audit"].includes(tab)) {
      window.history.replaceState(null, "", `${window.location.pathname}#${tab}`);
    }
  }, [tab]);

  useEffect(() => {
    setUserPage(1);
  }, [userFilter, roleFilter, authFilter, userLimit]);

  const fleetStats = useMemo(() => {
    const items = labFleet.data || [];
    return {
      total: items.length,
      active: items.filter((d) => (d.ready_replicas || 0) > 0).length,
      paused: items.filter((d) => d.is_paused || d.lifecycle_summary?.state === "paused").length,
      expired: items.filter((d) => d.expires_at && new Date(d.expires_at).getTime() <= Date.now()).length,
    };
  }, [labFleet.data]);

  const filteredFleet = useMemo(() => {
    const q = labFilter.toLowerCase();
    const type = labTypeFilter.toLowerCase();
    return (labFleet.data || []).filter(
      (d) => {
        const haystack = `${d.name} ${d.namespace} ${d.owner_username || ""} ${(d as Deployment & { owner_email?: string }).owner_email || ""}`.toLowerCase();
        const deploymentType = (d.deployment_type || d.type || "").toLowerCase();
        return (!q || haystack.includes(q)) && (!type || deploymentType === type);
      },
    );
  }, [labFleet.data, labFilter, labTypeFilter]);

  const labTypes = useMemo(() => {
    return Array.from(new Set((labFleet.data || []).map((d) => d.deployment_type || d.type).filter(Boolean))).sort();
  }, [labFleet.data]);

  const userTotalPages = (users.data || []).length >= userLimit ? userPage + 1 : userPage;

  return (
    <>
      <ToastContainer />
      <PageHeader title="Administration" subtitle="Gerer les utilisateurs, templates, configurations et labs etudiants." />

      <Tabs value={tab} onChange={setTab}>
        <TabList>
          <TabTrigger value="users"><Users size={16} /> Utilisateurs</TabTrigger>
          <TabTrigger value="catalog"><Boxes size={16} /> Catalogue</TabTrigger>
          <TabTrigger value="runtimes"><Wrench size={16} /> App Access</TabTrigger>
          <TabTrigger value="labs"><Activity size={16} /> Labs etudiants</TabTrigger>
          <TabTrigger value="audit"><FileJson size={16} /> Audit</TabTrigger>
        </TabList>

        <TabContent value="users">
          <section className="panel">
            <div className="section-head">
              <h2>Utilisateurs ({(users.data || []).length})</h2>
              <div className="actions-row">
                <Button variant="primary" onClick={() => { setEditUser(null); setShowUserDialog(true); }}>
                  <Plus size={16} /> Nouveau
                </Button>
                <Button onClick={() => setShowCsvImport(true)}><Upload size={16} /> CSV</Button>
              </div>
            </div>
            <div className="actions-row" style={{ gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
              <SearchBox placeholder="Rechercher..." value={userFilter} onChange={(e) => setUserFilter(e.target.value)} />
              <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} style={{ minHeight: 38, border: "1px solid var(--border)", borderRadius: 8, padding: "0 8px" }}>
                <option value="">Tous roles</option>
                <option value="student">Etudiant</option>
                <option value="teacher">Enseignant</option>
                <option value="admin">Admin</option>
              </select>
              <select value={authFilter} onChange={(e) => setAuthFilter(e.target.value)} style={{ minHeight: 38, border: "1px solid var(--border)", borderRadius: 8, padding: "0 8px" }}>
                <option value="">Tous providers</option>
                <option value="local">Local</option>
                <option value="oidc">SSO</option>
              </select>
              <select value={userLimit} onChange={(e) => setUserLimit(Number(e.target.value))} style={{ minHeight: 38, border: "1px solid var(--border)", borderRadius: 8, padding: "0 8px" }}>
                <option value={10}>10 / page</option>
                <option value={25}>25 / page</option>
                <option value={50}>50 / page</option>
                <option value={100}>100 / page</option>
              </select>
            </div>
            {users.isLoading ? <LoadingState /> : null}
            {users.error ? <ErrorState>Impossible de charger les utilisateurs.</ErrorState> : null}
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Nom</th>
                    <th>Email</th>
                    <th>Auth</th>
                    <th>Role</th>
                    <th>Statut</th>
                    <th>Cree le</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(users.data || []).map((user) => (
                    <tr key={user.id}>
                      <td>{user.id}</td>
                      <td>{user.full_name || user.username}</td>
                      <td>{user.email || "N/A"}</td>
                      <td><span className="badge">{authProviderLabel(user.auth_provider)}</span></td>
                      <td><span className="badge blue">{roleLabel(user.role)}</span></td>
                      <td><StatusBadge state={user.is_active ? "active" : "error"} /></td>
                      <td>{shortDate(user.created_at)}</td>
                      <td>
                        <div className="actions-row" style={{ gap: 4 }}>
                          <Button onClick={() => { setEditUser(user); setShowUserDialog(true); }}><Edit2 size={14} /></Button>
                          <Button onClick={() => setQuotaUser(user)}><Sliders size={14} /></Button>
                          <ConfirmDialog
                            destructive
                            title="Supprimer l'utilisateur"
                            description={`Supprimer ${user.username} definitivement ?`}
                            confirmLabel="Supprimer"
                            trigger={<Button variant="danger"><Trash2 size={14} /></Button>}
                            onConfirm={() => deleteUserMut.mutate(user.id)}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={userPage} totalPages={userTotalPages} onChange={setUserPage} />
          </section>
        </TabContent>

        <TabContent value="catalog">
          <section className="panel">
            <div className="section-head">
              <h2>Templates ({(templates.data || []).length})</h2>
              <Button variant="primary" onClick={() => { setEditTemplate(null); setShowTemplateDialog(true); }}>
                <Plus size={16} /> Nouveau template
              </Button>
            </div>
            {templates.isLoading ? <LoadingState /> : null}
            {templates.error ? <ErrorState /> : null}
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Nom</th>
                    <th>Type</th>
                    <th>Image</th>
                    <th>Port</th>
                    <th>Service</th>
                    <th>Tags</th>
                    <th>Actif</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(templates.data || []).map((t) => (
                    <tr key={String(t.key || t.id)}>
                      <td>{t.key}</td>
                      <td>{t.name}</td>
                      <td><span className="badge">{t.deployment_type}</span></td>
                      <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>{t.default_image}</td>
                      <td>{t.default_port}</td>
                      <td>{t.default_service_type}</td>
                      <td className="lab-meta">{(t.tags || []).map((tag) => <span className="badge" key={tag}>{tag}</span>)}</td>
                      <td><StatusBadge state={t.active ? "active" : "paused"} /></td>
                      <td>
                        <div className="actions-row">
                          <Button onClick={() => { setEditTemplate(t); setShowTemplateDialog(true); }}><Edit2 size={14} /></Button>
                          <ConfirmDialog
                            destructive
                            title="Supprimer le template"
                            description={`Supprimer definitivement ${t.name} ?`}
                            confirmLabel="Supprimer"
                            trigger={<Button variant="danger"><Trash2 size={14} /></Button>}
                            onConfirm={() => deleteTemplateMut.mutate(String(t.key || t.id))}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </TabContent>

        <TabContent value="runtimes">
          <section className="panel">
            <div className="section-head">
              <h2>Configurations runtime ({(runtimeConfigs.data || []).length})</h2>
              <Button variant="primary" onClick={() => { setEditRuntime(null); setShowRuntimeDialog(true); }}>
                <Plus size={16} /> Nouvelle config
              </Button>
            </div>
            {runtimeConfigs.isLoading ? <LoadingState /> : null}
            {runtimeConfigs.error ? <ErrorState /> : null}
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Image</th>
                    <th>Port</th>
                    <th>Service</th>
                    <th>CPU req/lim</th>
                    <th>Mem req/lim</th>
                    <th>Etudiants</th>
                    <th>Actif</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(runtimeConfigs.data || []).map((rc) => (
                    <tr key={rc.id}>
                      <td><strong>{rc.key}</strong></td>
                      <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>{rc.default_image}</td>
                      <td>{rc.target_port}</td>
                      <td>{rc.default_service_type}</td>
                      <td>{rc.min_cpu_request}/{rc.min_cpu_limit}</td>
                      <td>{rc.min_memory_request}/{rc.min_memory_limit}</td>
                      <td><StatusBadge state={rc.allowed_for_students ? "active" : "paused"} /></td>
                      <td><StatusBadge state={rc.active ? "active" : "paused"} /></td>
                      <td>
                        <div className="actions-row">
                          <Button onClick={() => { setEditRuntime(rc); setShowRuntimeDialog(true); }}><Edit2 size={14} /></Button>
                          <ConfirmDialog
                            destructive
                            title="Supprimer la config"
                            description={`Supprimer ${rc.key} ?`}
                            confirmLabel="Supprimer"
                            trigger={<Button variant="danger"><Trash2 size={14} /></Button>}
                            onConfirm={() => deleteRuntimeMut.mutate(rc.id)}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </TabContent>

        <TabContent value="labs">
          <section className="metric-grid">
            <MetricCard label="Total" value={fleetStats.total} icon={<Boxes size={18} />} />
            <MetricCard label="Actifs" value={fleetStats.active} icon={<Activity size={18} />} />
            <MetricCard label="En pause" value={fleetStats.paused} icon={<PauseCircle size={18} />} />
            <MetricCard label="Expires" value={fleetStats.expired} icon={<Activity size={18} />} />
          </section>
          <section className="panel" style={{ marginTop: 16 }}>
            <div className="section-head">
              <h2>Fleet etudiant ({filteredFleet.length}/{labFleet.data?.length || 0})</h2>
              <Button onClick={() => queryClient.invalidateQueries({ queryKey: ["deployments-all"] })}>
                <RefreshCw size={16} /> Actualiser
              </Button>
            </div>
            <div className="actions-row" style={{ gap: 10, marginBottom: 12 }}>
              <SearchBox placeholder="Nom, namespace, proprietaire..." value={labFilter} onChange={(e) => setLabFilter(e.target.value)} />
              <select value={labStatusFilter} onChange={(e) => setLabStatusFilter(e.target.value)} style={{ minHeight: 38, border: "1px solid var(--border)", borderRadius: 8, padding: "0 8px" }}>
                <option value="">Tous</option>
                <option value="active">Actifs</option>
                <option value="paused">En pause</option>
                <option value="expired">Expires</option>
              </select>
              <select value={labTypeFilter} onChange={(e) => setLabTypeFilter(e.target.value)} style={{ minHeight: 38, border: "1px solid var(--border)", borderRadius: 8, padding: "0 8px" }}>
                <option value="">Tous types</option>
                {labTypes.map((type) => <option value={type} key={type}>{type}</option>)}
              </select>
            </div>
            {labFleet.isLoading ? <LoadingState /> : null}
            {labFleet.error ? <ErrorState /> : null}
            {filteredFleet.length > 0 ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Nom</th>
                      <th>Proprietaire</th>
                      <th>Namespace</th>
                      <th>Type</th>
                      <th>Ready</th>
                      <th>TTL</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredFleet.map((d) => {
                      const paused = Boolean(d.is_paused || d.lifecycle_summary?.state === "paused");
                      return (
                        <tr key={`${d.namespace}-${d.name}`}>
                          <td><strong>{d.name}</strong></td>
                          <td>{d.owner_username || "N/A"}</td>
                          <td>{d.namespace}</td>
                          <td><span className="badge">{d.deployment_type || d.type || "custom"}</span></td>
                          <td>{d.ready_replicas || 0}/{d.replicas || 1}</td>
                          <td>{ttl(d.expires_at)}</td>
                          <td>
                            <div className="actions-row">
                              <Button onClick={() => lifecycleMut.mutate({ d, action: paused ? "resume" : "pause" })}>
                                {paused ? <PlayCircle size={14} /> : <PauseCircle size={14} />}
                              </Button>
                              <ConfirmDialog
                                destructive
                                title="Supprimer le lab"
                                description={`Supprimer ${d.name} ?`}
                                confirmLabel="Supprimer"
                                trigger={<Button variant="danger"><Trash2 size={14} /></Button>}
                                onConfirm={() => deleteLabMut.mutate(d)}
                              />
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        </TabContent>

        <TabContent value="audit">
          <AuditLogViewer />
        </TabContent>
      </Tabs>

      <UserDialog key={editUser?.id ?? "new"} user={editUser} ssoEnabled={Boolean(sso.data)} open={showUserDialog} onOpenChange={setShowUserDialog} />
      {quotaUser ? <QuotaDialog key={quotaUser.id} user={quotaUser} open={Boolean(quotaUser)} onOpenChange={(o) => { if (!o) setQuotaUser(null); }} /> : null}
      <CsvImportDialog open={showCsvImport} onOpenChange={setShowCsvImport} />
      <TemplateDialog key={editTemplate ? String(editTemplate.key ?? editTemplate.id) : "new"} template={editTemplate} open={showTemplateDialog} onOpenChange={setShowTemplateDialog} />
      <RuntimeConfigDialog key={editRuntime?.id ?? "new"} config={editRuntime} open={showRuntimeDialog} onOpenChange={setShowRuntimeDialog} />
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <QueryProvider>
    <AppShell page="admin" requireRole={["admin"]}>
      {() => <AdminPage />}
    </AppShell>
  </QueryProvider>,
);
