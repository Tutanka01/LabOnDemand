import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit2, Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { deleteTemplate, getAllTemplates } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { Template } from "../../types/api";
import { Button, ConfirmDialog, EmptyState, errorMessage, QueryState, SearchBox, showToast, SkeletonRows, StatusBadge } from "../ui";
import { type ColumnDef, DataTable } from "../DataTable";
import { TemplateDialog } from "./TemplateDialog";

/** Lab catalogue: every template, active or not. */
export function TemplatesTab() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [dialog, setDialog] = useState<{ open: boolean; template: Template | null }>({ open: false, template: null });
  const templates = useQuery({ queryKey: ["templates-all"], queryFn: getAllTemplates });

  const deleteMut = useMutation({
    mutationFn: (id: string | number) => deleteTemplate(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates-all"] });
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      showToast(t("admin.toast_template_deleted"), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("admin.error_delete_template")), "error"),
  });

  const columns = useMemo<ColumnDef<Template>[]>(
    () => [
      { id: "key", header: t("admin.col_key"), accessorFn: (tpl) => tpl.key ?? "" },
      { id: "name", header: t("admin.col_name"), accessorFn: (tpl) => tpl.name },
      {
        id: "type",
        header: t("admin.col_type"),
        accessorFn: (tpl) => tpl.deployment_type ?? "",
        cell: ({ row }) => <span className="badge">{row.original.deployment_type}</span>,
      },
      {
        id: "image",
        header: t("admin.col_image"),
        accessorFn: (tpl) => tpl.default_image ?? "",
        cell: ({ row }) => (
          <span className="truncate-cell" title={row.original.default_image ?? undefined}>
            {row.original.default_image}
          </span>
        ),
      },
      { id: "port", header: t("admin.col_port"), accessorFn: (tpl) => Number(tpl.default_port) || 0, cell: ({ row }) => row.original.default_port },
      { id: "service", header: t("admin.col_service"), accessorFn: (tpl) => tpl.default_service_type ?? "" },
      {
        id: "tags",
        header: t("admin.col_tags"),
        enableSorting: false,
        cell: ({ row }) => (
          <span className="lab-meta">
            {(row.original.tags || []).map((tag) => (
              <span className="badge" key={tag}>
                {tag}
              </span>
            ))}
          </span>
        ),
      },
      {
        id: "active",
        header: t("admin.col_active"),
        accessorFn: (tpl) => (tpl.active ? 1 : 0),
        cell: ({ row }) => <StatusBadge state={row.original.active ? "active" : "inactive"} />,
      },
      {
        id: "actions",
        header: t("students.actions"),
        enableSorting: false,
        cell: ({ row }) => {
          const template = row.original;
          return (
            <div className="actions-row">
              <Button
                onClick={() => setDialog({ open: true, template })}
                title={t("admin.edit_template")}
                aria-label={t("admin.edit_named", { name: template.name })}
              >
                <Edit2 size={14} aria-hidden="true" />
              </Button>
              <ConfirmDialog
                destructive
                title={t("admin.delete_template")}
                description={t("admin.delete_template_body", { name: template.name })}
                confirmLabel={t("common.delete")}
                trigger={
                  <Button
                    variant="danger"
                    disabled={template.id == null || (deleteMut.isPending && deleteMut.variables === template.id)}
                    title={t("admin.delete_template")}
                    aria-label={t("admin.delete_named", { name: template.name })}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </Button>
                }
                onConfirm={() => {
                  if (template.id != null) deleteMut.mutate(template.id);
                }}
              />
            </div>
          );
        },
      },
    ],
    [deleteMut, t],
  );

  const items = templates.data || [];
  const q = search.trim().toLowerCase();
  const filtered = q
    ? items.filter((tpl) =>
        `${tpl.key || ""} ${tpl.name} ${tpl.deployment_type || ""} ${tpl.default_image || ""} ${(tpl.tags || []).join(" ")}`
          .toLowerCase()
          .includes(q),
      )
    : items;
  const openCreate = () => setDialog({ open: true, template: null });

  return (
    <section className="panel">
      <div className="section-head">
        <h2>
          {t("admin.templates_title")}
          {templates.data ? ` (${items.length})` : ""}
        </h2>
        <Button variant="primary" onClick={openCreate}>
          <Plus size={16} aria-hidden="true" /> {t("admin.new_template")}
        </Button>
      </div>
      <QueryState
        query={templates}
        skeleton={<SkeletonRows rows={6} cols={7} />}
        errorTitle={t("admin.error_templates")}
        isEmpty={items.length === 0}
        empty={
          <EmptyState
            title={t("admin.templates_empty")}
            action={
              <Button variant="primary" onClick={openCreate}>
                <Plus size={16} aria-hidden="true" /> {t("admin.new_template")}
              </Button>
            }
          >
            {t("admin.templates_empty_hint")}
          </EmptyState>
        }
      >
        <div className="actions-row mb-3">
          <SearchBox placeholder={t("admin.templates_search")} value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {filtered.length ? (
          <DataTable
            data={filtered}
            columns={columns}
            getRowId={(tpl) => String(tpl.key ?? tpl.id)}
            label={t("admin.templates_title")}
          />
        ) : (
          <EmptyState title={t("admin.search_no_match")} />
        )}
      </QueryState>

      {/* Mounted only while open: each opening starts from the item's current values. */}
      {dialog.open ? (
        <TemplateDialog
          key={dialog.template ? String(dialog.template.key ?? dialog.template.id) : "new"}
          template={dialog.template}
          open
          onOpenChange={(open) => setDialog((prev) => ({ ...prev, open }))}
        />
      ) : null}
    </section>
  );
}
