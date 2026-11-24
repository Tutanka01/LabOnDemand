import { ArrowLeft, BookOpen, Monitor, Users } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../../lib/i18n";
import type { Assignment, Classroom, Template } from "../../types/api";
import { PageHeader } from "../AppShell";
import { Button, TabContent, TabList, Tabs, TabTrigger } from "../ui";
import { AddStudentDialog } from "./AddStudentDialog";
import { AssignmentDialog } from "./AssignmentDialog";
import { ClassroomAssignmentsTab } from "./ClassroomAssignmentsTab";
import { ClassroomMonitorTab } from "./ClassroomMonitorTab";
import { ClassroomStudentsTab } from "./ClassroomStudentsTab";
import { useClassroomAssignments, useClassroomStudents, useDistributeAssignment } from "./queries";

export const CLASSROOM_TABS = ["students", "assignments", "monitor"] as const;

/** One classroom: students, assignments and lab monitoring tabs. */
export function ClassroomDetail({
  classroom,
  templates,
  tab,
  onTabChange,
  onBack,
}: {
  classroom: Classroom;
  templates: Template[];
  tab: string;
  onTabChange: (tab: string) => void;
  onBack: () => void;
}) {
  const { t } = useI18n();
  const students = useClassroomStudents(classroom.id);
  const assignments = useClassroomAssignments(classroom.id);
  const distribution = useDistributeAssignment(classroom.id);

  const [showAddStudent, setShowAddStudent] = useState(false);
  const [assignmentDialog, setAssignmentDialog] = useState<{ open: boolean; assignment: Assignment | null }>({
    open: false,
    assignment: null,
  });

  const count = (n?: number) => (n === undefined ? "" : ` (${n})`);

  return (
    <>
      <PageHeader
        title={classroom.name}
        subtitle={classroom.description || t("teacher.class_management")}
        actions={
          <Button onClick={onBack}>
            <ArrowLeft size={16} aria-hidden="true" /> {t("correction.back")}
          </Button>
        }
      />

      <Tabs value={tab} onChange={onTabChange}>
        <TabList>
          <TabTrigger value="students">
            <Users size={16} aria-hidden="true" /> {t("students.title")}
            {count(students.data?.length)}
          </TabTrigger>
          <TabTrigger value="assignments">
            <BookOpen size={16} aria-hidden="true" /> {t("assignment.title")}
            {count(assignments.data?.length)}
          </TabTrigger>
          <TabTrigger value="monitor">
            <Monitor size={16} aria-hidden="true" /> {t("teacher.tab_monitor")}
          </TabTrigger>
        </TabList>

        <TabContent value="students">
          <ClassroomStudentsTab classroomId={classroom.id} onAdd={() => setShowAddStudent(true)} />
        </TabContent>

        <TabContent value="assignments">
          <ClassroomAssignmentsTab
            classroomId={classroom.id}
            studentCount={students.data?.length ?? 0}
            distribution={distribution}
            onCreate={() => setAssignmentDialog({ open: true, assignment: null })}
            onEdit={(assignment) => setAssignmentDialog({ open: true, assignment })}
          />
        </TabContent>

        <TabContent value="monitor">
          <ClassroomMonitorTab classroomId={classroom.id} />
        </TabContent>
      </Tabs>

      <AddStudentDialog classroomId={classroom.id} open={showAddStudent} onOpenChange={setShowAddStudent} />
      {/* Mounted only while open: a reused instance kept stale form values and an
          empty probe list, and saving it again wiped the assignment's tests. */}
      {assignmentDialog.open ? (
        <AssignmentDialog
          key={assignmentDialog.assignment?.id ?? "new"}
          classroomId={classroom.id}
          assignment={assignmentDialog.assignment}
          templates={templates}
          open
          onOpenChange={(open) => setAssignmentDialog((prev) => ({ ...prev, open }))}
        />
      ) : null}
    </>
  );
}
