import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useState } from "react";
import { importUsersCsv } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button, ErrorState, ModalShell, showToast } from "../ui";

type ImportResult = { created: number; skipped: number; errors: string[] };

/** Bulk user creation from a CSV file, with a per-row error report. */
export function CsvImportDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const mutation = useMutation({
    mutationFn: (csv: File) => importUsersCsv(csv),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      const normalized: ImportResult = {
        created: data.created ?? data.summary?.created ?? 0,
        skipped: data.skipped ?? data.summary?.skipped ?? 0,
        errors:
          data.errors ??
          (data.results || [])
            .filter((item) => item.status === "error")
            .map((item) => {
              const where = [item.line != null ? `#${item.line}` : "", item.username || ""].filter(Boolean).join(" ");
              const reason = item.detail || item.error || t("admin.csv_unknown_error");
              return where ? `${where}: ${reason}` : reason;
            }),
      };
      setResult(normalized);
      showToast(
        t("admin.toast_users_imported", { count: normalized.created }),
        normalized.errors.length ? "info" : "success",
      );
    },
  });

  const close = () => {
    setFile(null);
    setResult(null);
    mutation.reset();
    onOpenChange(false);
  };

  return (
    <ModalShell open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())} title={t("admin.csv_title")}>
      {result ? (
        <div className="grid gap-3">
          <div className="actions-row">
            <span className="badge green">{t("admin.csv_created", { count: result.created })}</span>
            <span className="badge amber">{t("admin.csv_skipped", { count: result.skipped })}</span>
            <span className="badge red">{t("admin.csv_errors", { count: result.errors.length })}</span>
          </div>
          {result.errors.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("admin.csv_error_details")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.errors.map((e, i) => (
                    <tr key={i}>
                      <td className="whitespace-normal">{e}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <div className="actions-row justify-end">
            <Button
              onClick={() => {
                setResult(null);
                setFile(null);
                mutation.reset();
              }}
            >
              {t("admin.csv_import_another")}
            </Button>
            <Button variant="primary" onClick={close}>
              {t("common.close")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid gap-4">
          <div className="field full">
            <label htmlFor="csv-file">{t("admin.csv_file_label")}</label>
            <input id="csv-file" type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </div>
          {mutation.error ? <ErrorState title={t("admin.error_import")} error={mutation.error} /> : null}
          <div className="actions-row justify-end">
            <Button onClick={close}>{t("common.cancel")}</Button>
            <Button variant="primary" disabled={!file || mutation.isPending} onClick={() => file && mutation.mutate(file)}>
              <Upload size={16} aria-hidden="true" /> {mutation.isPending ? t("teacher.importing") : t("common.import")}
            </Button>
          </div>
        </div>
      )}
    </ModalShell>
  );
}
