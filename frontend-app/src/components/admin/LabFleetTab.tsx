import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Boxes, PauseCircle, PlayCircle, RefreshCw, Timer, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { deleteDeployment, getAllDeployments, setDeploymentLifecycle } from "../../lib/api";
import { ttl } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { Deployment } from "../../types/api";
import { Button, ConfirmDialog, EmptyState, errorMessage, MetricCard, QueryState, SearchBox, showToast, SkeletonRows, StatusBadge } from "../ui";
import { type ColumnDef, DataTable } from "../DataTable";

type LifecycleAction = "pause" | "resume";

// Rows of `/deployments/all` are database records: `status` and `owner`, no live replica counts.
const isPaused = (d: Deployment) => d.status === "paused" || Boolean(d.is_paused);
const isExpired = (d: Deployment) => Boolean(d.expires_at && new Date(d.expires_at).getTime() <= Date.now());
const ownerName = (d: Deployment) => d.owner?.username || d.owner_username || "";
const deploymentType = (d: Deployment) => d.deployment_type || d.type || "";
const labKey = (d: Deployment) => `${d.namespace}/${d.name}`;
const rowId = (d: Deployment) => (d.id != null ? String(d.id) : labKey(d));

/** Every student lab running on the cluster, with pause / resume / delete. */
export function LabFleetTab() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const fleet = useQuery({
    queryKey: ["deployments-all", statusFilter],
    queryFn: () => getAllDeployments(statusFilter || undefined),
  });

  const invalidateFleet = () => queryClient.invalidateQueries({ queryKey: ["deployments-all"] });

  const deleteMut = useMutation({
    mutationFn: (d: Deployment) => deleteDeployment(d.namespace, d.name),
    onSuccess: (_data, d) => {
      invalidateFleet();
      showToast(t("admin.toast_lab_deleted", { name: d.name }), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("admin.error_delete_lab")), "error"),
  });

  const lifecycleMut = useMutation({
    mutationFn: ({ d, action }: { d: Deployment; action: LifecycleAction }) =>
      setDeploymentLifecycle(d.namespace, d.name, action),
    onSuccess: (_data, { d, action }) => {
      invalidateFleet();
      showToast(t(action === "pause" ? "admin.toast_lab_paused" : "admin.toast_lab_resumed", { name: d.name }), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("admin.error_lifecycle")), "error"),
  });

  // Soft-deleted records are history, not labs that can still be paused or deleted.
  const items = useMemo(() => (fleet.data || []).filter((d) => d.status !== "deleted"), [fleet.data]);
  const stats = useMemo(
    () => ({
      total: items.length,
      active: items.filter((d) => d.status === "active").length,
      paused: items.filter(isPaused).length,
      expired: items.filter(isExpired).length,
    }),
    [items],
  );
  const labTypes = useMemo(
    () => Array.from(new Set(items.map(deploymentType).filter(Boolean))).sort(),
    [items],
  );
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    const type = typeFilter.toLowerCase();
    return items.filter((d) => {
      const haystack = `${d.name} ${d.namespace} ${ownerName(d)} ${d.owner?.email || ""} ${d.owner?.full_name || ""}`.toLowerCase();
      return (!q || haystack.includes(q)) && (!type || deploymentType(d).toLowerCase() === type);
    });
  }, [items, search, typeFilter]);

  const isBusy = (d: Deployment) =>
    (deleteMut.isPending && deleteMut.variables && rowId(deleteMut.variables) === rowId(d)) ||
    (lifecycleMut.isPending && lifecycleMut.variables && rowId(lifecycleMut.variables.d) === rowId(d));

  const columns = useMemo<ColumnDef<Deployment>[]>(
    () => [
      {
        id: "name",
        header: t("admin.col_name"),
        accessorFn: (d) => d.name,
        cell: ({ row }) => <strong>{row.original.name}</strong>,
      },
      {
        id: "owner",
        header: t("admin.col_owner"),
        accessorFn: ownerName,
        cell: ({ row }) => ownerName(row.original) || <span className="muted">—</span>,
      },
      { id: "namespace", header: t("admin.col_namespace"), accessorFn: (d) => d.namespace },
      {
        id: "type",
        header: t("admin.col_type"),
        accessorFn: deploymentType,
        cell: ({ row }) => <span className="badge">{deploymentType(row.original) || "custom"}</span>,
      },
      {
        id: "status",
        header: t("submission.status"),
        accessorFn: (d) => d.status ?? "",
        cell: ({ row }) => <StatusBadge state={row.original.status} />,
      },
      {
        id: "ttl",
        header: t("admin.col_ttl"),
        accessorFn: (d) => d.expires_at ?? "",
        cell: ({ row }) => ttl(row.original.expires_at),
      },
      {
        id: "actions",
        header: t("students.actions"),
        enableSorting: false,
        cell: ({ row }) => {
          const d = row.original;
          const paused = isPaused(d);
          const busy = Boolean(isBusy(d));
          return (
            <div className="actions-row">
              {paused ? (
                <Button
                  disabled={busy}
                  onClick={() => lifecycleMut.mutate({ d, action: "resume" })}
                  title={t("dashboard.resume")}
                  aria-label={t("admin.resume_lab_named", { name: d.name })}
                >
                  <PlayCircle size={14} aria-hidden="true" />
                </Button>
              ) : (
                <ConfirmDialog
                  title={t("admin.pause_lab")}
                  description={t("admin.pause_lab_body", { name: d.name, owner: ownerName(d) || "—" })}
                  confirmLabel={t("dashboard.pause")}
                  trigger={
                    <Button
                      disabled={busy}
                      title={t("dashboard.pause")}
                      aria-label={t("admin.pause_lab_named", { name: d.name })}
                    >
                      <PauseCircle size={14} aria-hidden="true" />
                    </Button>
                  }
                  onConfirm={() => lifecycleMut.mutate({ d, action: "pause" })}
                />
              )}
              <ConfirmDialog
                destructive
                title={t("admin.delete_lab")}
                description={t("admin.delete_lab_body", { name: d.name, owner: ownerName(d) || "—" })}
                confirmLabel={t("common.delete")}
                trigger={
                  <Button
                    variant="danger"
                    disabled={busy}
                    title={t("admin.delete_lab")}
                    aria-label={t("admin.delete_named", { name: d.name })}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </Button>
                }
                onConfirm={() => deleteMut.mutate(d)}
              />
            </div>
          );
        },
      },
    ],
    [t, deleteMut, lifecycleMut],
  );

  const filtersActive = Boolean(search || statusFilter || typeFilter);

  return (
    <>
      {fleet.data ? (
        <section className="metric-grid">
          <MetricCard label={t("admin.metric_total")} value={stats.total} icon={<Boxes size={18} />} hint={t("admin.metric_deployed_labs")} />
          <MetricCard label={t("teacher.lab_filter_active")} value={stats.active} icon={<Activity size={18} />} hint={t("admin.metric_running")} />
          <MetricCard label={t("teacher.lab_filter_paused")} value={stats.paused} icon={<PauseCircle size={18} />} hint={t("teacher.metric_suspended")} />
          <MetricCard label={t("admin.metric_expired")} value={stats.expired} icon={<Timer size={18} />} hint={t("admin.metric_to_clean")} />
        </section>
      ) : null}
      <section className="panel mt-4">
        <div className="section-head">
          <h2>
            {t("admin.fleet_title")}
            {fleet.data ? ` (${filtered.length}/${items.length})` : ""}
          </h2>
          <Button onClick={() => void fleet.refetch()} disabled={fleet.isFetching}>
            <RefreshCw size={16} className={fleet.isFetching ? "animate-spin" : undefined} aria-hidden="true" />{" "}
            {t("overview.refresh")}
          </Button>
        </div>
        <div className="actions-row mb-3 gap-2.5">
          <SearchBox placeholder={t("admin.fleet_search")} value={search} onChange={(e) => setSearch(e.target.value)} />
          <select
            className="control"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label={t("overview.filter_status")}
          >
            <option value="">{t("overview.all_statuses")}</option>
            <option value="active">{t("teacher.lab_filter_active")}</option>
            <option value="paused">{t("teacher.lab_filter_paused")}</option>
            <option value="expired">{t("admin.metric_expired")}</option>
          </select>
          <select
            className="control"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            aria-label={t("admin.filter_type")}
          >
            <option value="">{t("admin.all_types")}</option>
            {labTypes.map((type) => (
              <option value={type} key={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
        <QueryState
          query={fleet}
          skeleton={<SkeletonRows rows={6} cols={7} />}
          errorTitle={t("admin.error_fleet")}
          isEmpty={filtered.length === 0}
          empty={
            filtersActive ? (
              <EmptyState title={t("admin.fleet_no_match")}>{t("admin.filters_no_match_hint")}</EmptyState>
            ) : (
              <EmptyState title={t("admin.fleet_empty")}>{t("admin.fleet_empty_hint")}</EmptyState>
            )
          }
        >
          <DataTable data={filtered} columns={columns} getRowId={rowId} label={t("admin.fleet_title")} />
        </QueryState>
      </section>
    </>
  );
}
