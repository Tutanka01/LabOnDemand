import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { Classroom } from "../../types/api";
import { createClassroom, importStudentsCsv, updateClassroom } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button, ErrorState, ModalShell, showToast } from "../ui";
import { useInvalidateClassroom } from "./queries";

// Validation messages are translation keys, resolved with t() when displayed.
const schema = z.object({
  name: z.string().min(2, "teacher.validation_min_2").max(100, "teacher.validation_max_100"),
  description: z.string().max(500, "teacher.validation_max_500").optional(),
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
  const { t } = useI18n();
  const invalidateClassroom = useInvalidateClassroom();
  const isEdit = Boolean(classroom);
  const [step, setStep] = useState<"form" | "csv">("form");
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const form = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { name: classroom?.name || "", description: classroom?.description || "" },
  });

  const close = () => {
    form.reset();
    setStep("form");
    setCsvFile(null);
    mutation.reset();
    csvImportMutation.reset();
    onOpenChange(false);
  };

  const createMutation = useMutation({
    mutationFn: (data: FormData) => createClassroom(data),
    onSuccess: () => {
      invalidateClassroom();
      showToast(t("teacher.toast_classroom_created"), "success");
      close();
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: FormData) => updateClassroom(classroom!.id, data),
    onSuccess: () => {
      invalidateClassroom();
      showToast(t("teacher.toast_classroom_updated"), "success");
      close();
    },
  });

  const csvImportMutation = useMutation({
    mutationFn: (file: File) => importStudentsCsv(classroom!.id, file),
    onSuccess: () => {
      invalidateClassroom(classroom!.id);
      showToast(t("teacher.toast_students_imported"), "success");
      setStep("form");
      setCsvFile(null);
    },
  });

  const mutation = isEdit ? updateMutation : createMutation;
  const submit = form.handleSubmit((data) => mutation.mutate(data));
  const nameError = form.formState.errors.name?.message;

  return (
    <ModalShell
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(true) : close())}
      title={isEdit ? t("teacher.edit_classroom") : t("classroom.create_title")}
    >
      {step === "form" ? (
        <form className="form-grid" onSubmit={submit} noValidate>
          {mutation.error ? (
            <div className="field full">
              <ErrorState title={t("teacher.error_save_classroom")} error={mutation.error} />
            </div>
          ) : null}
          <div className="field full">
            <label htmlFor="classroom-name">
              {t("classroom.name")}
              <span className="required"> *</span>
            </label>
            <input
              id="classroom-name"
              placeholder={t("classroom.name_placeholder")}
              aria-invalid={Boolean(nameError)}
              aria-describedby={nameError ? "classroom-name-error" : undefined}
              {...form.register("name")}
            />
            {nameError ? (
              <span id="classroom-name-error" className="badge red">
                {t(nameError)}
              </span>
            ) : null}
          </div>
          <div className="field full">
            <label htmlFor="classroom-description">{t("classroom.description")}</label>
            <textarea
              className="min-h-20 resize-y"
              id="classroom-description"
              rows={3}
              placeholder={t("classroom.description_placeholder")}
              {...form.register("description")}
            />
            {form.formState.errors.description?.message ? (
              <span className="badge red">{t(form.formState.errors.description.message)}</span>
            ) : null}
          </div>
          <div className="actions-row field full justify-between">
            {isEdit ? (
              <Button type="button" onClick={() => setStep("csv")}>
                <Upload size={16} aria-hidden="true" /> {t("students.import_csv")}
              </Button>
            ) : (
              <span />
            )}
            <div className="actions-row">
              <Button type="button" onClick={close}>
                {t("common.cancel")}
              </Button>
              <Button variant="primary" type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? t("assignment.saving") : isEdit ? t("assignment.update") : t("classroom.save")}
              </Button>
            </div>
          </div>
        </form>
      ) : (
        <div className="grid gap-4">
          <div className="field full">
            <label htmlFor="classroom-csv">{t("teacher.csv_file_students")}</label>
            <input
              id="classroom-csv"
              type="file"
              accept=".csv"
              onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
            />
          </div>
          {csvImportMutation.error ? (
            <ErrorState title={t("teacher.error_import")} error={csvImportMutation.error} />
          ) : null}
          <div className="actions-row justify-end">
            <Button onClick={() => setStep("form")}>{t("common.back")}</Button>
            <Button
              variant="primary"
              disabled={!csvFile || csvImportMutation.isPending}
              onClick={() => csvFile && csvImportMutation.mutate(csvFile)}
            >
              <Upload size={16} aria-hidden="true" />
              {csvImportMutation.isPending ? t("teacher.importing") : t("common.import")}
            </Button>
          </div>
        </div>
      )}
    </ModalShell>
  );
}
