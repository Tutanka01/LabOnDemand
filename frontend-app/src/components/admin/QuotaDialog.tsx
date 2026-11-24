import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { QuotaOverride, User } from "../../types/api";
import { deleteQuotaOverride, getQuotaOverride, setQuotaOverride } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button, ConfirmDialog, ErrorState, LoadingState, ModalShell, showToast } from "../ui";

type QuotaFields = { maxApps: string; maxCpu: string; maxMem: string; maxStorage: string; expiresAt: string };

const EMPTY_FIELDS: QuotaFields = { maxApps: "", maxCpu: "", maxMem: "", maxStorage: "", expiresAt: "" };

const NUMBER_FIELDS = [
  { key: "maxApps", label: "admin.quota_max_apps", min: 1 },
  { key: "maxCpu", label: "admin.quota_max_cpu", min: 100 },
  { key: "maxMem", label: "admin.quota_max_mem", min: 128 },
  { key: "maxStorage", label: "admin.quota_max_storage", min: 1 },
] as const;

/** Per-user quota override (falls back to the role defaults when unset). */
export function QuotaDialog({
  user,
  open,
  onOpenChange,
}: {
  user: User;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [fields, setFields] = useState<QuotaFields>(EMPTY_FIELDS);

  const existing = useQuery({
    queryKey: ["quota-override", user.id],
    queryFn: () => getQuotaOverride(user.id),
    enabled: open,
  });

  useEffect(() => {
    if (!open || !existing.data) return;
    const d = existing.data;
    setFields({
      maxApps: d.max_apps != null ? String(d.max_apps) : "",
      maxCpu: d.max_cpu_m != null ? String(d.max_cpu_m) : "",
      maxMem: d.max_mem_mi != null ? String(d.max_mem_mi) : "",
      maxStorage: d.max_storage_gi != null ? String(d.max_storage_gi) : "",
      expiresAt: d.expires_at ? d.expires_at.slice(0, 16) : "",
    });
  }, [existing.data, open]);

  const onDone = (message: string) => {
    queryClient.invalidateQueries({ queryKey: ["quota-override", user.id] });
    showToast(message, "success");
    onOpenChange(false);
  };

  const setMut = useMutation({
    mutationFn: () => {
      const override: QuotaOverride = {};
      if (fields.maxApps) override.max_apps = Number(fields.maxApps);
      if (fields.maxCpu) override.max_cpu_m = Number(fields.maxCpu);
      if (fields.maxMem) override.max_mem_mi = Number(fields.maxMem);
      if (fields.maxStorage) override.max_storage_gi = Number(fields.maxStorage);
      if (fields.expiresAt) override.expires_at = fields.expiresAt;
      return setQuotaOverride(user.id, override);
    },
    onSuccess: () => onDone(t("admin.toast_quota_saved")),
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteQuotaOverride(user.id),
    onSuccess: () => onDone(t("admin.toast_quota_removed")),
  });

  const hasOverride = Boolean(existing.data && Object.keys(existing.data).length > 0);
  const loadedWithoutOverride = existing.isSuccess && !hasOverride;
  const busy = setMut.isPending || deleteMut.isPending;
  const orDefault = (value?: number | null, unit = "") => (value ? `${value}${unit}` : t("admin.quota_default"));

  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={t("admin.quota_title", { name: user.username })}>
      {existing.isLoading ? <LoadingState /> : null}
      {existing.error ? (
        <ErrorState
          title={t("admin.error_quota")}
          error={existing.error}
          onRetry={() => void existing.refetch()}
          retrying={existing.isFetching}
        />
      ) : null}

      {loadedWithoutOverride ? <p className="muted mb-3.5">{t("admin.quota_none")}</p> : null}

      {existing.data && hasOverride ? (
        <div className="lab-meta mb-3.5">
          <span className="badge">{t("admin.quota_badge_apps", { value: orDefault(existing.data.max_apps) })}</span>
          <span className="badge">{t("admin.quota_badge_cpu", { value: orDefault(existing.data.max_cpu_m, "m") })}</span>
          <span className="badge">{t("admin.quota_badge_mem", { value: orDefault(existing.data.max_mem_mi, "Mi") })}</span>
          <span className="badge">{t("admin.quota_badge_storage", { value: orDefault(existing.data.max_storage_gi, "Gi") })}</span>
        </div>
      ) : null}

      <form
        className="form-grid"
        onSubmit={(e) => {
          e.preventDefault();
          setMut.mutate();
        }}
      >
        {NUMBER_FIELDS.map((field) => (
          <div className="field" key={field.key}>
            <label htmlFor={`quota-${field.key}`}>{t(field.label)}</label>
            <input
              id={`quota-${field.key}`}
              type="number"
              min={field.min}
              value={fields[field.key]}
              onChange={(e) => setFields((prev) => ({ ...prev, [field.key]: e.target.value }))}
              placeholder={t("admin.quota_role_default")}
            />
          </div>
        ))}
        <div className="field full">
          <label htmlFor="quota-expires">{t("admin.quota_expires")}</label>
          <input
            id="quota-expires"
            type="datetime-local"
            value={fields.expiresAt}
            onChange={(e) => setFields((prev) => ({ ...prev, expiresAt: e.target.value }))}
          />
        </div>

        {setMut.error ? (
          <div className="field full">
            <ErrorState title={t("admin.error_save_quota")} error={setMut.error} />
          </div>
        ) : null}
        {deleteMut.error ? (
          <div className="field full">
            <ErrorState title={t("admin.error_remove_quota")} error={deleteMut.error} />
          </div>
        ) : null}

        <div className="actions-row field full mt-2 justify-end gap-3">
          {hasOverride ? (
            <ConfirmDialog
              destructive
              title={t("admin.quota_remove")}
              description={t("admin.quota_remove_body", { name: user.username })}
              confirmLabel={t("admin.quota_remove")}
              trigger={
                <Button type="button" variant="danger" disabled={busy}>
                  <Trash2 size={14} aria-hidden="true" /> {t("admin.quota_remove")}
                </Button>
              }
              onConfirm={() => deleteMut.mutate()}
            />
          ) : null}
          <Button type="button" onClick={() => onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" type="submit" disabled={busy || existing.isLoading}>
            {setMut.isPending ? t("assignment.saving") : t("admin.quota_apply")}
          </Button>
        </div>
      </form>
    </ModalShell>
  );
}
