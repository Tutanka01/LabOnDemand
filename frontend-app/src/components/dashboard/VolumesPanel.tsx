import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, FolderTree, Loader2, Trash2 } from "lucide-react";
import { useState } from "react";
import { deletePvc, getPvcs } from "../../lib/api";
import { shortDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { PvcInfo, VolumeTarget } from "../../types/api";
import { Badge, Button, ConfirmDialog, EmptyState, IconButton, SkeletonRows, showToast } from "../ui";
import { QueryProblem, problemDetail } from "./QueryProblem";

/** The user's persistent volumes (files kept between labs), as a list that wraps on narrow screens. */
export function VolumesPanel({
  showNamespace,
  onBrowse,
}: {
  showNamespace: boolean;
  onBrowse: (target: VolumeTarget, title: string) => void;
}) {
  const { t, locale } = useI18n();
  const queryClient = useQueryClient();
  const pvcs = useQuery({ queryKey: ["pvcs"], queryFn: getPvcs });
  const [deleting, setDeleting] = useState<Set<string>>(() => new Set());

  const deleteMutation = useMutation({
    mutationFn: (pvc: PvcInfo) => deletePvc(pvc.name, Boolean(pvc.bound)),
    onMutate: (pvc) => setDeleting((current) => new Set(current).add(pvc.name)),
    onSuccess: (_data, pvc) => {
      // Drop it from the list right away; the refetch below confirms.
      queryClient.setQueryData<PvcInfo[]>(["pvcs"], (current) => current?.filter((item) => item.name !== pvc.name));
      showToast(t("volumes.deleted_toast", { name: pvc.name }), "success");
    },
    onError: (error, pvc) => showToast(t("volumes.delete_failed", { name: pvc.name, detail: problemDetail(error) }), "error"),
    onSettled: (_data, _error, pvc) => {
      setDeleting((current) => {
        const copy = new Set(current);
        copy.delete(pvc.name);
        return copy;
      });
      void queryClient.invalidateQueries({ queryKey: ["pvcs"] });
      void queryClient.invalidateQueries({ queryKey: ["quotas"] });
    },
  });

  const items = pvcs.data || [];

  return (
    <section className="panel" aria-labelledby="volumes-title">
      <div className="section-head">
        <div>
          <h2 id="volumes-title">{t("volumes.title")}</h2>
          <p className="muted m-0 text-[var(--text-sm)]">{t("volumes.subtitle")}</p>
        </div>
      </div>
      {pvcs.isLoading ? <SkeletonRows rows={3} cols={4} /> : null}
      {pvcs.error ? (
        <QueryProblem
          error={pvcs.error}
          title={t("volumes.load_error")}
          onRetry={() => void pvcs.refetch()}
          retrying={pvcs.isFetching}
          stale={Boolean(pvcs.data)}
        />
      ) : null}
      {pvcs.data && items.length === 0 ? <EmptyState title={t("volumes.empty_title")}>{t("volumes.empty_hint")}</EmptyState> : null}
      {items.length ? (
        <ul className="m-0 grid list-none gap-2 p-0">
          {items.map((pvc) => {
            const busy = deleting.has(pvc.name);
            const lastLab = pvc.last_bound_app || pvc.app_type;
            return (
              <li
                key={`${pvc.namespace ?? ""}/${pvc.name}`}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius)] border border-[var(--border)] p-3"
                aria-busy={busy}
              >
                <div className="flex min-w-0 flex-1 basis-56 items-center gap-2.5">
                  <Database size={18} className="shrink-0 text-[var(--muted)]" aria-hidden="true" />
                  <div className="min-w-0">
                    <strong className="block truncate text-[var(--text-sm)]">{pvc.name}</strong>
                    <span className="muted block truncate text-[var(--text-xs)]">
                      {[
                        pvc.storage,
                        lastLab ? t("volumes.last_lab_value", { lab: lastLab }) : null,
                        t("volumes.created_value", { date: shortDate(pvc.created_at, locale) }),
                        showNamespace && pvc.namespace ? pvc.namespace : null,
                        showNamespace && pvc.storage_class ? pvc.storage_class : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                </div>
                <Badge tone={pvc.bound ? "default" : "blue"}>{pvc.bound ? t("volumes.in_use") : t("volumes.available")}</Badge>
                <div className="ml-auto flex gap-1">
                  {pvc.namespace ? (
                    <IconButton
                      title={t("files.browse")}
                      aria-label={t("volumes.browse_named", { name: pvc.name })}
                      onClick={() => onBrowse({ namespace: pvc.namespace!, pvc: pvc.name }, pvc.name)}
                      disabled={busy}
                    >
                      <FolderTree size={15} aria-hidden="true" />
                    </IconButton>
                  ) : null}
                  <ConfirmDialog
                    destructive
                    title={t("volumes.delete_title")}
                    description={
                      pvc.bound
                        ? t("volumes.delete_description_bound", { name: pvc.name })
                        : t("volumes.delete_description", { name: pvc.name })
                    }
                    confirmLabel={t("common.delete")}
                    trigger={
                      <Button
                        variant="danger"
                        title={t("volumes.delete_title")}
                        aria-label={t("volumes.delete_named", { name: pvc.name })}
                        disabled={busy}
                      >
                        {busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Trash2 size={14} aria-hidden="true" />}
                      </Button>
                    }
                    onConfirm={() => deleteMutation.mutate(pvc)}
                  />
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
