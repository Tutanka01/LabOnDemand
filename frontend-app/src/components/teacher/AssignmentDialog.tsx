import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import type { Assignment, GradingMode, Template } from "../../types/api";
import { createAssignment, getGradingSpec, saveGradingSpec, updateAssignment } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import {
  Button,
  errorMessage,
  ErrorState,
  LoadingState,
  ModalShell,
  showToast,
  TabContent,
  TabList,
  Tabs,
  TabTrigger,
} from "../ui";
import {
  AssignmentContentForm,
  assignmentDefaults,
  type AssignmentFormData,
  assignmentSchema,
} from "./AssignmentContentForm";
import { type GradingSettings, ProbeEditor } from "./ProbeEditor";
import { useInvalidateClassroom } from "./queries";

type DialogTab = "content" | "tests";

const DEFAULT_TIMEOUT = 120;

function initialGrading(assignment?: Assignment | null): GradingSettings {
  return {
    probes: [],
    customScript: "",
    gradingMode: (assignment?.grading_mode as GradingMode) || "none",
    timeoutSeconds: DEFAULT_TIMEOUT,
  };
}

/** Create or edit an assignment (statement tab + automatic tests tab). */
export function AssignmentDialog({
  classroomId,
  assignment,
  templates,
  open,
  onOpenChange,
}: {
  classroomId: number;
  assignment?: Assignment | null;
  templates: Template[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const invalidateClassroom = useInvalidateClassroom();
  const isEdit = Boolean(assignment);
  const [activeTab, setActiveTab] = useState<DialogTab>("content");
  const [grading, setGrading] = useState<GradingSettings>(() => initialGrading(assignment));

  const form = useForm<AssignmentFormData>({
    resolver: zodResolver(assignmentSchema),
    defaultValues: assignmentDefaults(assignment),
  });

  // Existing grading spec (edit mode only). null = the assignment has no spec yet.
  const specQuery = useQuery({
    queryKey: ["grading-spec", classroomId, assignment?.id],
    queryFn: () => getGradingSpec(classroomId, assignment!.id),
    enabled: isEdit && Boolean(assignment?.id) && open,
    staleTime: 30_000,
  });
  const specLoaded = !isEdit || specQuery.isSuccess;
  const hadSpec = Boolean(specQuery.data);

  useEffect(() => {
    if (specQuery.data) {
      const spec = specQuery.data;
      setGrading((prev) => ({
        ...prev,
        probes: spec.checks ?? [],
        customScript: spec.custom_script ?? "",
        timeoutSeconds: spec.timeout_seconds ?? DEFAULT_TIMEOUT,
      }));
    }
  }, [specQuery.data]);

  const specPayload = () => ({
    timeout_seconds: grading.timeoutSeconds,
    checks: grading.probes,
    custom_script: grading.customScript.trim() || null,
  });

  /**
   * Saves the tests alongside the assignment. Skipped when there is nothing to save, unless
   * an existing spec must be emptied, and never when the existing spec failed to load (it
   * would be overwritten with what the dialog could not show).
   */
  const saveSpec = async (assignmentId: number) => {
    if (!specLoaded) return;
    const empty = grading.probes.length === 0 && !grading.customScript.trim();
    if (empty && !hadSpec) return;
    await saveGradingSpec(classroomId, assignmentId, specPayload());
  };

  const close = () => {
    form.reset(assignmentDefaults(assignment));
    setGrading(initialGrading(assignment));
    setActiveTab("content");
    createMut.reset();
    updateMut.reset();
    saveSpecMut.reset();
    onOpenChange(false);
  };

  const onSaved = (message: string) => {
    invalidateClassroom(classroomId);
    showToast(message, "success");
    close();
  };

  const createMut = useMutation({
    mutationFn: async (data: AssignmentFormData) => {
      const created = await createAssignment(classroomId, {
        title: data.title,
        instructions: data.instructions,
        deliverables: data.deliverables,
        template_key: data.template_key,
        cpu_preset: data.cpu_preset,
        ram_preset: data.ram_preset,
        due_at: data.due_at || undefined,
        grading_mode: grading.gradingMode,
      });
      await saveSpec(created.id);
      return created;
    },
    onSuccess: () => onSaved(t("assignment.created_ok")),
  });

  const updateMut = useMutation({
    mutationFn: async (data: AssignmentFormData) => {
      await updateAssignment(classroomId, assignment!.id, { ...data, grading_mode: grading.gradingMode });
      await saveSpec(assignment!.id);
      queryClient.invalidateQueries({ queryKey: ["grading-spec", classroomId, assignment!.id] });
    },
    onSuccess: () => onSaved(t("assignment.updated_ok")),
  });

  // Save only the tests in edit mode, without touching the assignment fields.
  const saveSpecMut = useMutation({
    mutationFn: () => saveGradingSpec(classroomId, assignment!.id, specPayload()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["grading-spec", classroomId, assignment!.id] });
      showToast(t("probe.saved_ok"), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("teacher.error_save_tests")), "error"),
  });

  const mutation = isEdit ? updateMut : createMut;

  // Called from the footer button and from Enter in the form; works from either tab
  // and brings the statement tab back when a field is invalid.
  const submit = () =>
    void form.handleSubmit(
      (data) => mutation.mutate(data),
      () => setActiveTab("content"),
    )();

  return (
    <ModalShell
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(true) : close())}
      title={isEdit ? t("assignment.edit_title") : t("assignment.create_title")}
      wide
    >
      {mutation.error ? <ErrorState title={t("teacher.error_save_assignment")} error={mutation.error} /> : null}

      <Tabs value={activeTab} onChange={(v) => setActiveTab(v as DialogTab)}>
        <TabList>
          <TabTrigger value="content">
            <FileText size={14} aria-hidden="true" /> {t("assignment.statement")}
          </TabTrigger>
          <TabTrigger value="tests">
            {t("probe.tab_title")}
            {grading.probes.length > 0 && <span className="badge ml-1.5">{grading.probes.length}</span>}
          </TabTrigger>
        </TabList>

        <TabContent value="content">
          <AssignmentContentForm form={form} templates={templates} onSubmit={submit} />
        </TabContent>

        <TabContent value="tests">
          {isEdit && specQuery.isLoading ? <LoadingState /> : null}
          {isEdit && specQuery.isError ? (
            <ErrorState
              title={t("teacher.error_load_tests")}
              error={specQuery.error}
              onRetry={() => void specQuery.refetch()}
              retrying={specQuery.isFetching}
            />
          ) : null}
          {specLoaded ? <ProbeEditor value={grading} onChange={setGrading} /> : null}
        </TabContent>
      </Tabs>

      <div className="actions-row field full justify-end mt-4">
        <Button type="button" onClick={close}>
          {t("common.cancel")}
        </Button>
        {isEdit && activeTab === "tests" && specLoaded ? (
          <Button type="button" onClick={() => saveSpecMut.mutate()} disabled={saveSpecMut.isPending}>
            {saveSpecMut.isPending ? t("probe.saving") : t("probe.save")}
          </Button>
        ) : null}
        <Button variant="primary" type="button" onClick={submit} disabled={mutation.isPending}>
          <Upload size={16} aria-hidden="true" />
          {mutation.isPending ? t("assignment.saving") : isEdit ? t("assignment.update") : t("assignment.create")}
        </Button>
      </div>
    </ModalShell>
  );
}
