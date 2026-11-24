import { useMutation } from "@tanstack/react-query";
import { Search, Upload, UserPlus } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { User } from "../../types/api";
import { createAndEnrollStudent, enrollStudents, importStudentsCsv, searchStudents } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button, EmptyState, ErrorState, LoadingState, ModalShell, showToast } from "../ui";
import { useInvalidateClassroom } from "./queries";

interface AddStudentDialogProps {
  classroomId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Mode = "search" | "create" | "csv";

const EMPTY_STUDENT = { username: "", email: "", full_name: "", password: "" };

export function AddStudentDialog({ classroomId, open, onOpenChange }: AddStudentDialogProps) {
  const { t } = useI18n();
  const invalidateClassroom = useInvalidateClassroom();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<Mode>("search");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [newStudent, setNewStudent] = useState(EMPTY_STUDENT);

  const searchMutation = useMutation({ mutationFn: (q: string) => searchStudents(q) });

  const close = () => {
    setQuery("");
    setSelected(new Set());
    setMode("search");
    setCsvFile(null);
    setNewStudent(EMPTY_STUDENT);
    searchMutation.reset();
    enrollMutation.reset();
    csvMutation.reset();
    createMutation.reset();
    onOpenChange(false);
  };

  const enrollMutation = useMutation({
    mutationFn: (userIds: number[]) => enrollStudents(classroomId, userIds),
    onSuccess: () => {
      invalidateClassroom(classroomId);
      showToast(t("teacher.toast_students_enrolled"), "success");
      close();
    },
  });

  const csvMutation = useMutation({
    mutationFn: (file: File) => importStudentsCsv(classroomId, file),
    onSuccess: () => {
      invalidateClassroom(classroomId);
      showToast(t("teacher.toast_students_imported"), "success");
      close();
    },
  });

  const createMutation = useMutation({
    mutationFn: () => createAndEnrollStudent(classroomId, newStudent),
    onSuccess: () => {
      invalidateClassroom(classroomId);
      showToast(t("teacher.toast_student_created"), "success");
      close();
    },
  });

  const doSearch = () => {
    if (query.trim()) searchMutation.mutate(query);
  };

  const toggleUser = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const results: User[] = searchMutation.data || [];
  const updateStudent = (key: keyof typeof EMPTY_STUDENT, value: string) =>
    setNewStudent((prev) => ({ ...prev, [key]: value }));

  const modes: Array<{ value: Mode; icon: ReactNode; label: string }> = [
    { value: "search", icon: <Search size={16} aria-hidden="true" />, label: t("teacher.add_mode_search") },
    { value: "create", icon: <UserPlus size={16} aria-hidden="true" />, label: t("teacher.add_mode_create") },
    { value: "csv", icon: <Upload size={16} aria-hidden="true" />, label: t("teacher.add_mode_csv") },
  ];

  return (
    <ModalShell open={open} onOpenChange={(o) => (o ? onOpenChange(true) : close())} title={t("teacher.add_students_title")}>
      <div className="actions-row mb-3.5" role="group" aria-label={t("teacher.add_mode_label")}>
        {modes.map((m) => (
          <Button
            key={m.value}
            variant={mode === m.value ? "primary" : "default"}
            aria-pressed={mode === m.value}
            onClick={() => setMode(m.value)}
          >
            {m.icon} {m.label}
          </Button>
        ))}
      </div>

      {mode === "search" ? (
        <div className="grid gap-3.5">
          <form
            className="actions-row"
            onSubmit={(e) => {
              e.preventDefault();
              doSearch();
            }}
          >
            <input
              className="control flex-1"
              placeholder={t("students.search_placeholder")}
              aria-label={t("students.search_label")}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Button
              type="submit"
              variant="primary"
              disabled={!query.trim() || searchMutation.isPending}
              aria-label={t("teacher.search_students")}
            >
              <Search size={16} aria-hidden="true" />
            </Button>
          </form>
          {searchMutation.isPending ? <LoadingState label={t("teacher.searching")} /> : null}
          {searchMutation.error ? <ErrorState title={t("teacher.error_search")} error={searchMutation.error} /> : null}
          {results.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>
                      <span className="sr-only">{t("teacher.col_select")}</span>
                    </th>
                    <th>{t("teacher.col_name")}</th>
                    <th>{t("students.email")}</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selected.has(user.id)}
                          onChange={() => toggleUser(user.id)}
                          aria-label={t("teacher.select_student", { name: user.full_name || user.username })}
                        />
                      </td>
                      <td>{user.full_name || user.username}</td>
                      <td>{user.email || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : searchMutation.isSuccess ? (
            <EmptyState title={t("teacher.search_no_student")}>{t("teacher.search_no_student_hint")}</EmptyState>
          ) : null}
          {enrollMutation.error ? <ErrorState title={t("teacher.error_enroll")} error={enrollMutation.error} /> : null}
          <div className="actions-row justify-end">
            <Button onClick={close}>{t("common.cancel")}</Button>
            <Button
              variant="primary"
              disabled={selected.size === 0 || enrollMutation.isPending}
              onClick={() => enrollMutation.mutate([...selected])}
            >
              {enrollMutation.isPending ? t("teacher.enrolling") : t("teacher.enroll_count", { count: selected.size })}
            </Button>
          </div>
        </div>
      ) : mode === "create" ? (
        <form
          className="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
        >
          <div className="field">
            <label htmlFor="new-student-username">
              {t("students.username")}
              <span className="required"> *</span>
            </label>
            <input
              id="new-student-username"
              required
              autoComplete="off"
              value={newStudent.username}
              onChange={(e) => updateStudent("username", e.target.value)}
              placeholder="jean.dupont"
            />
          </div>
          <div className="field">
            <label htmlFor="new-student-email">
              {t("students.email")}
              <span className="required"> *</span>
            </label>
            <input
              id="new-student-email"
              type="email"
              required
              value={newStudent.email}
              onChange={(e) => updateStudent("email", e.target.value)}
              placeholder="jean.dupont@univ.fr"
            />
          </div>
          <div className="field">
            <label htmlFor="new-student-name">{t("teacher.full_name")}</label>
            <input
              id="new-student-name"
              value={newStudent.full_name}
              onChange={(e) => updateStudent("full_name", e.target.value)}
              placeholder="Jean Dupont"
            />
          </div>
          <div className="field">
            <label htmlFor="new-student-password">
              {t("teacher.initial_password")}
              <span className="required"> *</span>
            </label>
            <input
              id="new-student-password"
              type="password"
              required
              autoComplete="new-password"
              aria-describedby="new-student-password-hint"
              value={newStudent.password}
              onChange={(e) => updateStudent("password", e.target.value)}
            />
          </div>
          <p id="new-student-password-hint" className="muted field full">
            {t("teacher.password_rules")}
          </p>
          {createMutation.error ? (
            <div className="field full">
              <ErrorState title={t("teacher.error_create_student")} error={createMutation.error} />
            </div>
          ) : null}
          <div className="actions-row field full justify-end">
            <Button type="button" onClick={() => setMode("search")}>
              {t("common.back")}
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={!newStudent.username || !newStudent.email || !newStudent.password || createMutation.isPending}
            >
              {createMutation.isPending ? t("teacher.creating") : t("teacher.create_and_enroll")}
            </Button>
          </div>
        </form>
      ) : (
        <div className="grid gap-3.5">
          <div className="field full">
            <label htmlFor="student-csv">{t("teacher.csv_file_students")}</label>
            <input id="student-csv" type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] || null)} />
          </div>
          {csvMutation.error ? <ErrorState title={t("teacher.error_import")} error={csvMutation.error} /> : null}
          <div className="actions-row justify-end">
            <Button onClick={() => setMode("search")}>{t("common.back")}</Button>
            <Button
              variant="primary"
              disabled={!csvFile || csvMutation.isPending}
              onClick={() => csvFile && csvMutation.mutate(csvFile)}
            >
              <Upload size={16} aria-hidden="true" />
              {csvMutation.isPending ? t("teacher.importing") : t("common.import")}
            </Button>
          </div>
        </div>
      )}
    </ModalShell>
  );
}
