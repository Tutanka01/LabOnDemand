import "../styles/main.css";
import { useQuery } from "@tanstack/react-query";
import { GraduationCap, LayoutGrid, Monitor, Plus, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "../components/AppShell";
import { Button, QueryState, SkeletonRows, TabContent, TabList, TabTrigger, Tabs } from "../components/ui";
import { ClassroomDetail, CLASSROOM_TABS } from "../components/teacher/ClassroomDetail";
import { ClassroomDialog } from "../components/teacher/ClassroomDialog";
import { ClassroomsTab } from "../components/teacher/ClassroomsTab";
import { GlobalMonitorTab } from "../components/teacher/GlobalMonitorTab";
import { TeacherOverviewTab } from "../components/teacher/TeacherOverviewTab";
import type { Classroom } from "../types/api";
import { getClassrooms, getTemplates } from "../lib/api";
import { useI18n } from "../lib/i18n";

const HOME_TABS = ["overview", "classrooms", "monitor"] as const;

function initialTab(): string {
  return (
    window.location.hash?.replace("#", "") ||
    new URLSearchParams(window.location.search).get("tab") ||
    "overview"
  );
}

export default function TeacherPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState(initialTab);
  const [selectedClassroomId, setSelectedClassroomId] = useState<number | null>(null);
  const [classroomDialog, setClassroomDialog] = useState<{ open: boolean; classroom: Classroom | null }>({
    open: false,
    classroom: null,
  });

  const classrooms = useQuery({ queryKey: ["classrooms"], queryFn: getClassrooms });
  const templates = useQuery({ queryKey: ["templates"], queryFn: getTemplates });
  const selectedClassroom = classrooms.data?.find((c) => c.id === selectedClassroomId) || null;

  useEffect(() => {
    const allowed: readonly string[] = selectedClassroom ? CLASSROOM_TABS : HOME_TABS;
    if (allowed.includes(tab)) window.history.replaceState(null, "", `${window.location.pathname}#${tab}`);
  }, [selectedClassroom, tab]);

  const openCreateClassroom = () => setClassroomDialog({ open: true, classroom: null });

  if (selectedClassroom) {
    return (
      <ClassroomDetail
        classroom={selectedClassroom}
        templates={templates.data || []}
        tab={tab}
        onTabChange={setTab}
        onBack={() => {
          setSelectedClassroomId(null);
          setTab("classrooms");
        }}
      />
    );
  }

  return (
    <>
      <PageHeader
        title={t("classroom.title")}
        subtitle={t("teacher.page_subtitle")}
        actions={
          <>
            <Button variant="primary" onClick={openCreateClassroom}>
              <Plus size={16} aria-hidden="true" /> {t("classroom.new")}
            </Button>
            <Button onClick={() => void classrooms.refetch()} disabled={classrooms.isFetching}>
              <RefreshCw size={16} className={classrooms.isFetching ? "animate-spin" : undefined} aria-hidden="true" />{" "}
              {t("overview.refresh")}
            </Button>
          </>
        }
      />

      <Tabs value={(HOME_TABS as readonly string[]).includes(tab) ? tab : "overview"} onChange={setTab}>
        <TabList>
          <TabTrigger value="overview">
            <LayoutGrid size={16} aria-hidden="true" /> {t("teacher.tab_overview")}
          </TabTrigger>
          <TabTrigger value="classrooms">
            <GraduationCap size={16} aria-hidden="true" /> {t("classroom.title")}
          </TabTrigger>
          <TabTrigger value="monitor">
            <Monitor size={16} aria-hidden="true" /> {t("teacher.tab_monitor")}
          </TabTrigger>
        </TabList>

        <TabContent value="overview">
          <TeacherOverviewTab onCreateClassroom={openCreateClassroom} />
        </TabContent>

        <TabContent value="classrooms">
          <ClassroomsTab
            classrooms={classrooms}
            onCreate={openCreateClassroom}
            onEdit={(classroom) => setClassroomDialog({ open: true, classroom })}
            onSelect={(id) => {
              setSelectedClassroomId(id);
              setTab("students");
            }}
          />
        </TabContent>

        <TabContent value="monitor">
          <QueryState query={classrooms} skeleton={<SkeletonRows rows={5} cols={5} />} errorTitle={t("teacher.error_classrooms")}>
            <GlobalMonitorTab classrooms={classrooms.data || []} />
          </QueryState>
        </TabContent>
      </Tabs>

      {/* Mounted only while open: each opening starts from the item's current values. */}
      {classroomDialog.open ? (
        <ClassroomDialog
          key={classroomDialog.classroom?.id ?? "new"}
          classroom={classroomDialog.classroom}
          open
          onOpenChange={(open) => setClassroomDialog((prev) => ({ ...prev, open }))}
        />
      ) : null}
    </>
  );
}
