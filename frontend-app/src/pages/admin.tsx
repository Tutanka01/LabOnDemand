import "../styles/main.css";
import { Activity, Boxes, FileJson, Users, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "../components/AppShell";
import { TabContent, TabList, TabTrigger, Tabs } from "../components/ui";
import { AuditLogViewer } from "../components/admin/AuditLogViewer";
import { LabFleetTab } from "../components/admin/LabFleetTab";
import { RuntimeConfigsTab } from "../components/admin/RuntimeConfigsTab";
import { TemplatesTab } from "../components/admin/TemplatesTab";
import { UsersTab } from "../components/admin/UsersTab";
import { useI18n } from "../lib/i18n";

const ADMIN_TABS = ["users", "catalog", "runtimes", "labs", "audit"] as const;

function initialTab(): string {
  const requested =
    window.location.hash?.replace("#", "") || new URLSearchParams(window.location.search).get("tab") || "users";
  return (ADMIN_TABS as readonly string[]).includes(requested) ? requested : "users";
}

export default function AdminPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState(initialTab);

  useEffect(() => {
    window.history.replaceState(null, "", `${window.location.pathname}#${tab}`);
  }, [tab]);

  return (
    <>
      <PageHeader title={t("header.admin")} subtitle={t("admin.page_subtitle")} />

      <Tabs value={tab} onChange={setTab}>
        <TabList>
          <TabTrigger value="users">
            <Users size={16} aria-hidden="true" /> {t("admin.tab_users")}
          </TabTrigger>
          <TabTrigger value="catalog">
            <Boxes size={16} aria-hidden="true" /> {t("admin.tab_catalog")}
          </TabTrigger>
          <TabTrigger value="runtimes">
            <Wrench size={16} aria-hidden="true" /> {t("admin.tab_runtimes")}
          </TabTrigger>
          <TabTrigger value="labs">
            <Activity size={16} aria-hidden="true" /> {t("admin.tab_labs")}
          </TabTrigger>
          <TabTrigger value="audit">
            <FileJson size={16} aria-hidden="true" /> {t("admin.tab_audit")}
          </TabTrigger>
        </TabList>

        <TabContent value="users">
          <UsersTab />
        </TabContent>
        <TabContent value="catalog">
          <TemplatesTab />
        </TabContent>
        <TabContent value="runtimes">
          <RuntimeConfigsTab />
        </TabContent>
        <TabContent value="labs">
          <LabFleetTab />
        </TabContent>
        <TabContent value="audit">
          <AuditLogViewer />
        </TabContent>
      </Tabs>
    </>
  );
}
