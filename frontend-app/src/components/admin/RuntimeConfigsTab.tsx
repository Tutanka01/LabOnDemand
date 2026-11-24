import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit2, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { deleteRuntimeConfig, getRuntimeConfigs } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { RuntimeConfig } from "../../types/api";
import { Button, ConfirmDialog, EmptyState, errorMessage, QueryState, showToast, SkeletonRows, StatusBadge } from "../ui";
import { type ColumnDef, DataTable } from "../DataTable";
import { RuntimeConfigDialog } from "./RuntimeConfigDialog";

/** Runtime configurations ("App Access"): image, port and minimum resources per runtime key. */
export function RuntimeConfigsTab() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<{ open: boolean; config: RuntimeConfig | null }>({ open: false, config: null });
  const runtimeConfigs = useQuery({ queryKey: ["runtime-configs"], queryFn: getRuntimeConfigs });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteRuntimeConfig(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runtime-configs"] });
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      queryClient.invalidateQueries({ queryKey: ["resource-presets"] });
      showToast(t("admin.toast_runtime_deleted"), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("admin.error_delete_runtime")), "error"),
  });

  const columns = useMemo<ColumnDef<RuntimeConfig>[]>(
    () => [
      {
        id: "key",
        header: t("admin.col_key"),
        accessorFn: (rc) => rc.key,
        cell: ({ row }) => <strong>{row.original.key}</strong>,
      },
      {
        id: "image",
        header: t("admin.col_image"),
        accessorFn: (rc) => rc.default_image,
        cell: ({ row }) => (
          <span className="truncate-cell" title={row.original.default_image}>
            {row.original.default_image}
          </span>
        ),
      },
      { id: "port", header: t("admin.col_port"), accessorFn: (rc) => rc.target_port },
      { id: "service", header: t("admin.col_service"), accessorFn: (rc) => rc.default_service_type },
      {
        id: "cpu",
        header: t("admin.col_cpu_req_lim"),
        enableSorting: false,
        cell: ({ row }) => `${row.original.min_cpu_request}/${row.original.min_cpu_limit}`,
      },
      {
        id: "mem",
        header: t("admin.col_mem_req_lim"),
        enableSorting: false,
        cell: ({ row }) => `${row.original.min_memory_request}/${row.original.min_memory_limit}`,
      },
      {
        id: "students",
        header: t("admin.col_students_allowed"),
        accessorFn: (rc) => (rc.allowed_for_students ? 1 : 0),
        cell: ({ row }) => <StatusBadge state={row.original.allowed_for_students ? "active" : "inactive"} />,
      },
      {
        id: "active",
        header: t("admin.col_active"),
        accessorFn: (rc) => (rc.active ? 1 : 0),
        cell: ({ row }) => <StatusBadge state={row.original.active ? "active" : "inactive"} />,
      },
      {
        id: "actions",
        header: t("students.actions"),
        enableSorting: false,
        cell: ({ row }) => {
          const rc = row.original;
          return (
            <div className="actions-row">
              <Button
                onClick={() => setDialog({ open: true, config: rc })}
                title={t("admin.edit_runtime")}
                aria-label={t("admin.edit_named", { name: rc.key })}
              >
                <Edit2 size={14} aria-hidden="true" />
              </Button>
              <ConfirmDialog
                destructive
                title={t("admin.delete_runtime")}
                description={t("admin.delete_runtime_body", { name: rc.key })}
                confirmLabel={t("common.delete")}
                trigger={
                  <Button
                    variant="danger"
                    disabled={deleteMut.isPending && deleteMut.variables === rc.id}
                    title={t("admin.delete_runtime")}
                    aria-label={t("admin.delete_named", { name: rc.key })}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </Button>
                }
                onConfirm={() => deleteMut.mutate(rc.id)}
              />
            </div>
          );
        },
      },
    ],
    [deleteMut, t],
  );

  const items = runtimeConfigs.data || [];
  const openCreate = () => setDialog({ open: true, config: null });

  return (
    <section className="panel">
      <div className="section-head">
        <h2>
          {t("admin.runtimes_title")}
          {runtimeConfigs.data ? ` (${items.length})` : ""}
        </h2>
        <Button variant="primary" onClick={openCreate}>
          <Plus size={16} aria-hidden="true" /> {t("admin.new_runtime")}
        </Button>
      </div>
      <QueryState
        query={runtimeConfigs}
        skeleton={<SkeletonRows rows={6} cols={7} />}
        errorTitle={t("admin.error_runtimes")}
        isEmpty={items.length === 0}
        empty={
          <EmptyState
            title={t("admin.runtimes_empty")}
            action={
              <Button variant="primary" onClick={openCreate}>
                <Plus size={16} aria-hidden="true" /> {t("admin.new_runtime")}
              </Button>
            }
          >
            {t("admin.runtimes_empty_hint")}
          </EmptyState>
        }
      >
        <DataTable data={items} columns={columns} getRowId={(rc) => String(rc.id)} label={t("admin.runtimes_title")} />
      </QueryState>

      {/* Mounted only while open: each opening starts from the item's current values. */}
      {dialog.open ? (
        <RuntimeConfigDialog
          key={dialog.config?.id ?? "new"}
          config={dialog.config}
          open
          onOpenChange={(open) => setDialog((prev) => ({ ...prev, open }))}
        />
      ) : null}
    </section>
  );
}
