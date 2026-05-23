import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, X } from "lucide-react";
import { useState } from "react";
import { importUsersCsv } from "../../lib/api";
import { Button, ErrorState, IconButton, showToast } from "../ui";

export function CsvImportDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<{ created: number; skipped: number; errors: string[] } | null>(null);

  const mutation = useMutation({
    mutationFn: (file: File) => importUsersCsv(file),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      const normalized = {
        created: data.created ?? data.summary?.created ?? 0,
        skipped: data.skipped ?? data.summary?.skipped ?? 0,
        errors: data.errors ?? (data.results || []).filter((item) => item.status === "error").map((item) => item.error || "Erreur inconnue"),
      };
      setResult(normalized);
      showToast(`${normalized.created} utilisateurs importes`, "success");
    },
  });

  const reset = () => {
    setFile(null);
    setResult(null);
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>Importer des utilisateurs (CSV)</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          {result ? (
            <div className="grid gap-3">
              <div className="actions-row">
                <span className="badge green">Crees: {result.created}</span>
                <span className="badge amber">Ignorés: {result.skipped}</span>
                <span className="badge red">Erreurs: {result.errors.length}</span>
              </div>
              {result.errors.length > 0 ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Erreurs</th></tr></thead>
                    <tbody>{result.errors.map((e, i) => <tr key={i}><td>{e}</td></tr>)}</tbody>
                  </table>
                </div>
              ) : null}
              <Button onClick={() => onOpenChange(false)}>Fermer</Button>
            </div>
          ) : (
            <div className="grid gap-4">
              <div className="field full">
                <label htmlFor="csv-file">Fichier CSV (format: username,email,full_name,password,role)</label>
                <input id="csv-file" type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] || null)} />
              </div>
              {mutation.error ? <ErrorState>{mutation.error.message}</ErrorState> : null}
              <div className="actions-row justify-end">
                <Button onClick={() => onOpenChange(false)}>Annuler</Button>
                <Button variant="primary" disabled={!file || mutation.isPending} onClick={() => file && mutation.mutate(file)}>
                  <Upload size={16} /> {mutation.isPending ? "Import..." : "Importer"}
                </Button>
              </div>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
