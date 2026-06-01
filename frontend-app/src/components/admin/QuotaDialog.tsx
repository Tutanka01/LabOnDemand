import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { QuotaOverride, User } from "../../types/api";
import { deleteQuotaOverride, getQuotaOverride, setQuotaOverride } from "../../lib/api";
import { Button, ErrorState, IconButton, LoadingState, showToast } from "../ui";

export function QuotaDialog({
  user,
  open,
  onOpenChange,
}: {
  user: User;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();

  const existing = useQuery({
    queryKey: ["quota-override", user.id],
    queryFn: () => getQuotaOverride(user.id),
    enabled: open,
  });

  const [maxApps, setMaxApps] = useState("");
  const [maxCpu, setMaxCpu] = useState("");
  const [maxMem, setMaxMem] = useState("");
  const [maxStorage, setMaxStorage] = useState("");
  const [expiresAt, setExpiresAt] = useState("");

  useEffect(() => {
    if (!open || !existing.data) return;
    setMaxApps(existing.data.max_apps != null ? String(existing.data.max_apps) : "");
    setMaxCpu(existing.data.max_cpu_m != null ? String(existing.data.max_cpu_m) : "");
    setMaxMem(existing.data.max_mem_mi != null ? String(existing.data.max_mem_mi) : "");
    setMaxStorage(existing.data.max_storage_gi != null ? String(existing.data.max_storage_gi) : "");
    setExpiresAt(existing.data.expires_at ? existing.data.expires_at.slice(0, 16) : "");
  }, [existing.data, open]);

  const setMut = useMutation({
    mutationFn: () => {
      const override: QuotaOverride = {};
      if (maxApps) override.max_apps = Number(maxApps);
      if (maxCpu) override.max_cpu_m = Number(maxCpu);
      if (maxMem) override.max_mem_mi = Number(maxMem);
      if (maxStorage) override.max_storage_gi = Number(maxStorage);
      if (expiresAt) override.expires_at = expiresAt;
      return setQuotaOverride(user.id, override);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quota-override", user.id] });
      showToast("Quota modifié", "success");
      onOpenChange(false);
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteQuotaOverride(user.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quota-override", user.id] });
      showToast("Override supprimé", "success");
      onOpenChange(false);
    },
  });

  const hasOverride = Boolean(existing.data && Object.keys(existing.data).length > 0);
  const loadedWithoutOverride = !existing.isLoading && !existing.error && !hasOverride;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>Quota override: {user.username}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          {existing.isLoading ? <LoadingState /> : null}
          {existing.error ? <ErrorState>Impossible de charger l'override.</ErrorState> : null}

          {loadedWithoutOverride && (
            <p className="muted">Aucun override défini. Les valeurs par défaut du rôle s'appliquent.</p>
          )}

          {existing.data && hasOverride && (
            <div className="lab-meta mb-3.5">
              <span className="badge">Apps: {existing.data.max_apps || "défaut"}</span>
              <span className="badge">CPU: {existing.data.max_cpu_m || "défaut"}m</span>
              <span className="badge">Mémoire: {existing.data.max_mem_mi || "défaut"}Mi</span>
              <span className="badge">Stockage: {existing.data.max_storage_gi || "défaut"}Gi</span>
            </div>
          )}

          <div className="form-grid">
            <div className="field">
              <label>Max apps</label>
              <input type="number" min={1} value={maxApps} onChange={(e) => setMaxApps(e.target.value)} placeholder="Défaut rôle" />
            </div>
            <div className="field">
              <label>Max CPU (m)</label>
              <input type="number" min={100} value={maxCpu} onChange={(e) => setMaxCpu(e.target.value)} placeholder="Défaut rôle" />
            </div>
            <div className="field">
              <label>Max mémoire (Mi)</label>
              <input type="number" min={128} value={maxMem} onChange={(e) => setMaxMem(e.target.value)} placeholder="Défaut rôle" />
            </div>
            <div className="field">
              <label>Max stockage (Gi)</label>
              <input type="number" min={1} value={maxStorage} onChange={(e) => setMaxStorage(e.target.value)} placeholder="Défaut rôle" />
            </div>
            <div className="field full">
              <label>Expiration (optionnel)</label>
              <input type="datetime-local" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
            </div>
          </div>

          {setMut.error ? <ErrorState>{setMut.error.message}</ErrorState> : null}

          <div className="actions-row mt-4 justify-end gap-3">
            {hasOverride ? (
              <Button variant="danger" onClick={() => deleteMut.mutate()} disabled={deleteMut.isPending}>
                <Trash2 size={14} /> Supprimer l'override
              </Button>
            ) : null}
            <Button onClick={() => onOpenChange(false)}>Annuler</Button>
            <Button variant="primary" disabled={setMut.isPending} onClick={() => setMut.mutate()}>
              {setMut.isPending ? "Enregistrement..." : "Appliquer"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
