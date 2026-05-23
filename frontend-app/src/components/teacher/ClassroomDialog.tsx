import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { Classroom } from "../../types/api";
import { createClassroom, importStudentsCsv, updateClassroom } from "../../lib/api";
import { Button, ErrorState, IconButton, showToast } from "../ui";

const schema = z.object({
  name: z.string().min(2, "Minimum 2 caracteres").max(100),
  description: z.string().max(500).optional(),
});

type FormData = z.infer<typeof schema>;

export function ClassroomDialog({
  classroom,
  open,
  onOpenChange,
}: {
  classroom?: Classroom | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const isEdit = Boolean(classroom);
  const [step, setStep] = useState<"form" | "csv">("form");
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { name: classroom?.name || "", description: classroom?.description || "" },
  });

  const createMutation = useMutation({
    mutationFn: (data: FormData) => createClassroom(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classrooms"] });
      showToast("Classe creee", "success");
      onOpenChange(false);
      resetAndClose();
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: FormData) => updateClassroom(classroom!.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classrooms"] });
      showToast("Classe mise a jour", "success");
      onOpenChange(false);
      resetAndClose();
    },
  });

  const csvImportMutation = useMutation({
    mutationFn: (file: File) => importStudentsCsv(classroom!.id, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classroom-students"] });
      showToast("Etudiants importes", "success");
      setStep("form");
      setCsvFile(null);
    },
  });

  const resetAndClose = () => {
    form.reset();
    setStep("form");
    setCsvFile(null);
  };

  const mutation = isEdit ? updateMutation : createMutation;
  const submit = form.handleSubmit((data) => mutation.mutate(data));

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) resetAndClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{isEdit ? "Modifier la classe" : "Nouvelle classe"}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          {mutation.error ? <ErrorState>{mutation.error.message}</ErrorState> : null}

          {step === "form" ? (
            <form className="form-grid" onSubmit={submit}>
              <div className="field full">
                <label htmlFor="name">Nom de la classe</label>
                <input id="name" {...form.register("name")} />
                {form.formState.errors.name ? <span className="badge red">{form.formState.errors.name.message}</span> : null}
              </div>
              <div className="field full">
                <label htmlFor="description">Description (optionnelle)</label>
                <textarea className="min-h-20 resize-y" id="description" rows={3} {...form.register("description")} />
              </div>
              <div className="actions-row field full justify-between">
                {isEdit ? (
                  <Button type="button" onClick={() => setStep("csv")}>
                    <Upload size={16} /> Importer etudiants (CSV)
                  </Button>
                ) : (
                  <span />
                )}
                <div className="actions-row">
                  <Button type="button" onClick={() => onOpenChange(false)}>Annuler</Button>
                  <Button variant="primary" type="submit" disabled={mutation.isPending}>
                    {mutation.isPending ? "Enregistrement..." : isEdit ? "Mettre a jour" : "Creer"}
                  </Button>
                </div>
              </div>
            </form>
          ) : (
            <div className="grid gap-4">
              <div className="field full">
                <label htmlFor="csv">Fichier CSV (format: username,email,full_name)</label>
                <input
                  id="csv"
                  type="file"
                  accept=".csv"
                  onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
                />
              </div>
              {csvImportMutation.error ? <ErrorState>{csvImportMutation.error.message}</ErrorState> : null}
              <div className="actions-row justify-end">
                <Button onClick={() => setStep("form")}>Retour</Button>
                <Button
                  variant="primary"
                  disabled={!csvFile || csvImportMutation.isPending}
                  onClick={() => csvFile && csvImportMutation.mutate(csvFile)}
                >
                  {csvImportMutation.isPending ? "Import..." : "Importer"}
                </Button>
              </div>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
