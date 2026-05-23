import { useQuery } from "@tanstack/react-query";
import { BarChart3, BookOpen, Boxes, LayoutDashboard, LogOut, Shield, UserCircle, Users } from "lucide-react";
import { type ReactNode, useEffect } from "react";
import { getCurrentUser, logout } from "../lib/api";
import { displayName, roleLabel } from "../lib/format";
import { RuntimeIcon } from "../lib/icons";
import { IconButton, LoadingState, SearchBox } from "./ui";

const nav = [
  { href: "index.html", label: "Dashboard", icon: LayoutDashboard, roles: ["student", "teacher", "admin"] },
  { href: "teacher.html", label: "Classes", icon: Users, roles: ["teacher", "admin"] },
  { href: "admin.html", label: "Administration", icon: Shield, roles: ["admin"] },
  { href: "admin-stats.html", label: "Stats cluster", icon: BarChart3, roles: ["admin"] }
];

export function AppShell({
  page,
  children,
  requireRole
}: {
  page: "dashboard" | "teacher" | "admin" | "admin-stats";
  children: (user: Awaited<ReturnType<typeof getCurrentUser>>) => ReactNode;
  requireRole?: Array<"admin" | "teacher" | "student">;
}) {
  const userQuery = useQuery({ queryKey: ["me"], queryFn: getCurrentUser, retry: false });

  useEffect(() => {
    if (userQuery.error) window.location.href = "login.html";
  }, [userQuery.error]);

  useEffect(() => {
    const user = userQuery.data;
    if (user && requireRole && !requireRole.includes(user.role)) window.location.href = "access-denied.html";
  }, [requireRole, userQuery.data]);

  if (!userQuery.data) return <LoadingState label="Verification de la session" />;

  const user = userQuery.data;
  const allowedNav = nav.filter((item) => item.roles.includes(user.role));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="index.html">
          <span className="brand-mark">
            <RuntimeIcon type="flask" />
          </span>
          <span>LabOnDemand</span>
        </a>
        <nav className="nav" aria-label="Navigation principale">
          {allowedNav.map((item) => {
            const Icon = item.icon;
            const active = item.href.replace(".html", "") === (page === "dashboard" ? "index" : page);
            return (
              <a className={active ? "active" : ""} href={item.href} key={item.href}>
                <Icon size={17} />
                {item.label}
              </a>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <strong>Mode clair uniquement</strong>
          <span>Interface SaaS compacte pour gerer les environnements de TP.</span>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <SearchBox placeholder="Rechercher un lab, volume ou template" />
          <div className="top-actions">
            <a className="icon-btn" href="documentation/README.md" title="Documentation">
              <BookOpen size={17} />
            </a>
            <span className="user-chip" id="username-display">
              <UserCircle size={18} />
              <span>
                {displayName(user)} · {roleLabel(user.role)}
              </span>
            </span>
            <IconButton
              id="logout-btn"
              title="Deconnexion"
              onClick={async () => {
                await logout();
                window.location.href = "login.html";
              }}
            >
              <LogOut size={17} />
            </IconButton>
          </div>
        </header>
        <div className="content">{children(user)}</div>
      </main>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="page-title">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p className="sub">{subtitle}</p> : null}
      </div>
      {actions ? <div className="actions-row">{actions}</div> : null}
    </div>
  );
}

export function PlaceholderPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel">
      <div className="section-head">
        <h2>{title}</h2>
        <Boxes size={18} className="muted" />
      </div>
      <p className="muted">{children}</p>
    </section>
  );
}
