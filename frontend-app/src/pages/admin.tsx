import "../styles/main.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  Boxes,
  Edit2,
  FileJson,
  Plus,
  RefreshCw,
  Sliders,
  Trash2,
  Upload,
  Users,
  Wrench,
  PlayCircle,
  PauseCircle,
} from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "../components/AppShell";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  MetricCard,
  Pagination,
  SearchBox,
  SkeletonRows,
  StatusBadge,
  TabContent,
  TabList,
  TabTrigger,
  Tabs,
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
import { authProviderLabel, roleLabel, shortDate, ttl } from "../lib/format";
import { useI18n } from "../lib/i18n";

export default function AdminPage() {
  const queryClient = useQueryClient();
  const { locale, t } = useI18n();

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
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["users"] }); showToast(locale === "fr" ? "Utilisateur supprimé" : "User deleted", "success"); },
  });

  const deleteTemplateMut = useMutation({
    mutationFn: (id: string | number) => deleteTemplate(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates-all"] });
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      showToast(locale === "fr" ? "Template supprimé" : "Template deleted", "success");
    },
  });

  const deleteRuntimeMut = useMutation({
    mutationFn: (id: number) => deleteRuntimeConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runtime-configs"] });
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      queryClient.invalidateQueries({ queryKey: ["resource-presets"] });
      showToast(locale === "fr" ? "Configuration supprimée" : "Configuration deleted", "success");
    },
  });

  const deleteLabMut = useMutation({
    mutationFn: (d: Deployment) => deleteDeployment(d.namespace, d.name),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["deployments-all"] }); showToast(locale === "fr" ? "Lab supprimé" : "Lab deleted", "success"); },
  });

  const lifecycleMut = useMutation({
    mutationFn: ({ d, action }: { d: Deployment; action: "pause" | "resume" }) =>
      setDeploymentLifecycle(d.namespace, d.name, action),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["deployments-all"] }); showToast(locale === "fr" ? "Action exécutée" : "Action executed", "success"); },
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
      <PageHeader title={t("header.admin")} subtitle={locale === "fr" ? "Gérer les utilisateurs, templates, configurations et labs étudiants." : "Manage users, templates, configurations, and student labs."} />

      <Tabs value={tab} onChange={setTab}>
        <TabList>
          <TabTrigger value="users"><Users size={16} /> {locale === "fr" ? "Utilisateurs" : "Users"}</TabTrigger>
          <TabTrigger value="catalog"><Boxes size={16} /> {locale === "fr" ? "Catalogue" : "Catalog"}</TabTrigger>
          <TabTrigger value="runtimes"><Wrench size={16} /> App Access</TabTrigger>
          <TabTrigger value="labs"><Activity size={16} /> {locale === "fr" ? "Labs étudiants" : "Student labs"}</TabTrigger>
          <TabTrigger value="audit"><FileJson size={16} /> Audit</TabTrigger>
        </TabList>

        <TabContent value="users">
          <section className="panel">
            <div className="section-head">
              <h2>{locale === "fr" ? `Utilisateurs (${(users.data || []).length})` : `Users (${(users.data || []).length})`}</h2>
              <div className="actions-row">
                <Button variant="primary" onClick={() => { setEditUser(null); setShowUserDialog(true); }}>
                  <Plus size={16} /> {locale === "fr" ? "Nouveau" : "New"}
                </Button>
                <Button onClick={() => setShowCsvImport(true)}><Upload size={16} /> CSV</Button>
              </div>
            </div>
            <div className="actions-row mb-3 gap-2.5">
              <SearchBox placeholder={t("common.search")} value={userFilter} onChange={(e) => setUserFilter(e.target.value)} />
              <select className="control" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                <option value="">{locale === "fr" ? "Tous rôles" : "All roles"}</option>
                <option value="student">{locale === "fr" ? "Étudiant" : "Student"}</option>
                <option value="teacher">{locale === "fr" ? "Enseignant" : "Teacher"}</option>
                <option value="admin">Admin</option>
              </select>
              <select className="control" value={authFilter} onChange={(e) => setAuthFilter(e.target.value)}>
                <option value="">{locale === "fr" ? "Tous providers" : "All providers"}</option>
                <option value="local">Local</option>
                <option value="oidc">SSO</option>
              </select>
              <select className="control" value={userLimit} onChange={(e) => setUserLimit(Number(e.target.value))}>
                <option value={10}>10 / page</option>
                <option value={25}>25 / page</option>
                <option value={50}>50 / page</option>
                <option value={100}>100 / page</option>
              </select>
            </div>
            {users.isLoading ? <SkeletonRows rows={8} cols={6} /> : null}
            {users.error ? <ErrorState>{locale === "fr" ? "Impossible de charger les utilisateurs." : "Unable to load users."}</ErrorState> : null}
            <div className="table-wrap" hidden={users.isLoading}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>{locale === "fr" ? "Nom" : "Name"}</th>
                    <th>Email</th>
                    <th>Auth</th>
                    <th>Role</th>
                    <th>{locale === "fr" ? "Statut" : "Status"}</th>
                    <th>{locale === "fr" ? "Créé le" : "Created at"}</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {!users.isLoading && !users.error && (users.data || []).length === 0 ? (
                    <tr><td colSpan={8}>{locale === "fr" ? "Aucun utilisateur ne correspond aux filtres." : "No user matches filters."}</td></tr>
                  ) : null}
                  {(users.data || []).map((user) => (
                    <tr key={user.id}>
                      <td>{user.id}</td>
                      <td>{user.full_name || user.username}</td>
                      <td>{user.email || "N/A"}</td>
                      <td><span className="badge">{authProviderLabel(user.auth_provider)}</span></td>
                      <td><span className="badge blue">{roleLabel(user.role, locale)}</span></td>
                      <td><StatusBadge state={user.is_active ? "active" : "inactive"} /></td>
                      <td>{shortDate(user.created_at)}</td>
                      <td>
                        <div className="actions-row gap-1">
                          <Button onClick={() => { setEditUser(user); setShowUserDialog(true); }}><Edit2 size={14} /></Button>
                          <Button onClick={() => setQuotaUser(user)}><Sliders size={14} /></Button>
                          <ConfirmDialog
                            destructive
                            title={locale === "fr" ? "Supprimer l'utilisateur" : "Delete user"}
                            description={locale === "fr" ? `Supprimer ${user.username} définitivement ?` : `Delete ${user.username} permanently?`}
                            confirmLabel={t("common.delete")}
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
                <Plus size={16} /> {locale === "fr" ? "Nouveau template" : "New template"}
              </Button>
            </div>
            {templates.isLoading ? <SkeletonRows rows={6} cols={7} /> : null}
            {templates.error ? <ErrorState /> : null}
            <div className="table-wrap" hidden={templates.isLoading}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>{locale === "fr" ? "Nom" : "Name"}</th>
                    <th>Type</th>
                    <th>Image</th>
                    <th>Port</th>
                    <th>Service</th>
                    <th>Tags</th>
                    <th>{locale === "fr" ? "Actif" : "Active"}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {!templates.isLoading && !templates.error && (templates.data || []).length === 0 ? (
                    <tr><td colSpan={9}>{locale === "fr" ? "Aucun template configuré." : "No template configured."}</td></tr>
                  ) : null}
                  {(templates.data || []).map((template) => (
                    <tr key={String(template.key || template.id)}>
                      <td>{template.key}</td>
                      <td>{template.name}</td>
                      <td><span className="badge">{template.deployment_type}</span></td>
                      <td className="truncate-cell">{template.default_image}</td>
                      <td>{template.default_port}</td>
                      <td>{template.default_service_type}</td>
                      <td className="lab-meta">{(template.tags || []).map((tag) => <span className="badge" key={tag}>{tag}</span>)}</td>
                      <td><StatusBadge state={template.active ? "active" : "paused"} /></td>
                      <td>
                        <div className="actions-row">
                          <Button onClick={() => { setEditTemplate(template); setShowTemplateDialog(true); }}><Edit2 size={14} /></Button>
                          <ConfirmDialog
                            destructive
                            title={locale === "fr" ? "Supprimer le template" : "Delete template"}
                            description={locale === "fr" ? `Supprimer définitivement ${template.name} ?` : `Permanently delete ${template.name}?`}
                            confirmLabel={t("common.delete")}
                            trigger={<Button variant="danger"><Trash2 size={14} /></Button>}
                            onConfirm={() => {
                              if (template.id != null) deleteTemplateMut.mutate(template.id);
                            }}
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
                <Plus size={16} /> {locale === "fr" ? "Nouvelle config" : "New config"}
              </Button>
            </div>
            {runtimeConfigs.isLoading ? <SkeletonRows rows={6} cols={7} /> : null}
            {runtimeConfigs.error ? <ErrorState /> : null}
            <div className="table-wrap" hidden={runtimeConfigs.isLoading}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Image</th>
                    <th>Port</th>
                    <th>Service</th>
                    <th>CPU req/lim</th>
                    <th>Mem req/lim</th>
                    <th>{locale === "fr" ? "Étudiants" : "Students"}</th>
                    <th>{locale === "fr" ? "Actif" : "Active"}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {!runtimeConfigs.isLoading && !runtimeConfigs.error && (runtimeConfigs.data || []).length === 0 ? (
                    <tr><td colSpan={9}>{locale === "fr" ? "Aucune configuration runtime." : "No runtime configuration."}</td></tr>
                  ) : null}
                  {(runtimeConfigs.data || []).map((rc) => (
                    <tr key={rc.id}>
                      <td><strong>{rc.key}</strong></td>
                      <td className="truncate-cell">{rc.default_image}</td>
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
                            title={locale === "fr" ? "Supprimer la config" : "Delete config"}
                            description={locale === "fr" ? `Supprimer ${rc.key} ?` : `Delete ${rc.key}?`}
                            confirmLabel={t("common.delete")}
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
            {[
              { label: "Total", value: fleetStats.total, icon: <Boxes size={18} />, hint: locale === "fr" ? "Labs déployés" : "Deployed labs" },
              { label: locale === "fr" ? "Actifs" : "Active", value: fleetStats.active, icon: <Activity size={18} />, hint: locale === "fr" ? "En cours d'exécution" : "Currently running" },
              { label: locale === "fr" ? "En pause" : "Paused", value: fleetStats.paused, icon: <PauseCircle size={18} />, hint: locale === "fr" ? "Suspendus" : "Suspended" },
              { label: locale === "fr" ? "Expirés" : "Expired", value: fleetStats.expired, icon: <Activity size={18} />, hint: locale === "fr" ? "À nettoyer" : "To clean up" },
            ].map((m, i) => (
              <motion.div
                key={m.label}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] }}
              >
                <MetricCard label={m.label} value={m.value} icon={m.icon} hint={m.hint} />
              </motion.div>
            ))}
          </section>
          <section className="panel mt-4">
            <div className="section-head">
              <h2>{locale === "fr" ? `Fleet étudiant (${filteredFleet.length}/${labFleet.data?.length || 0})` : `Student fleet (${filteredFleet.length}/${labFleet.data?.length || 0})`}</h2>
              <Button onClick={() => queryClient.invalidateQueries({ queryKey: ["deployments-all"] })}>
                <RefreshCw size={16} /> {t("overview.refresh")}
              </Button>
            </div>
            <div className="actions-row mb-3 gap-2.5">
              <SearchBox placeholder={locale === "fr" ? "Nom, namespace, propriétaire..." : "Name, namespace, owner..."} value={labFilter} onChange={(e) => setLabFilter(e.target.value)} />
              <select className="control" value={labStatusFilter} onChange={(e) => setLabStatusFilter(e.target.value)}>
                <option value="">{locale === "fr" ? "Tous" : "All"}</option>
                <option value="active">{locale === "fr" ? "Actifs" : "Active"}</option>
                <option value="paused">{locale === "fr" ? "En pause" : "Paused"}</option>
                <option value="expired">{locale === "fr" ? "Expirés" : "Expired"}</option>
              </select>
              <select className="control" value={labTypeFilter} onChange={(e) => setLabTypeFilter(e.target.value)}>
                <option value="">{locale === "fr" ? "Tous types" : "All types"}</option>
                {labTypes.map((type) => <option value={type} key={type}>{type}</option>)}
              </select>
            </div>
            {labFleet.isLoading ? <SkeletonRows rows={6} cols={7} /> : null}
            {labFleet.error ? <ErrorState /> : null}
            {filteredFleet.length > 0 ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{locale === "fr" ? "Nom" : "Name"}</th>
                      <th>{locale === "fr" ? "Propriétaire" : "Owner"}</th>
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
                                title={locale === "fr" ? "Supprimer le lab" : "Delete lab"}
                                description={locale === "fr" ? `Supprimer ${d.name} ?` : `Delete ${d.name}?`}
                                confirmLabel={t("common.delete")}
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
            ) : !labFleet.isLoading && !labFleet.error ? (
              <EmptyState title={locale === "fr" ? "Aucun lab" : "No labs"}>
                {locale === "fr" ? "Aucun lab étudiant ne correspond aux filtres." : "No student lab matches filters."}
              </EmptyState>
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
