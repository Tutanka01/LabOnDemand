import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, BookOpen, Boxes, Globe2, LayoutDashboard, LogOut, Moon, Shield, Sun, UserCircle, Users, X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { changePassword, getCurrentUser, logout, updateProfile } from "../lib/api";
import { displayName, roleLabel } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { RuntimeIcon } from "../lib/icons";
import { useThemePreference } from "../lib/theme";
import { Button, ErrorState, IconButton, LoadingState, SearchBox, showToast } from "./ui";

const nav = [
  { href: "index.html", labelKey: "dashboard", icon: LayoutDashboard, roles: ["student", "teacher", "admin"] },
  { href: "teacher.html", labelKey: "classes", icon: Users, roles: ["teacher", "admin"] },
  { href: "admin.html", labelKey: "administration", icon: Shield, roles: ["admin"] },
  { href: "admin-stats.html", labelKey: "clusterStats", icon: BarChart3, roles: ["admin"] }
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
  const queryClient = useQueryClient();
  const userQuery = useQuery({ queryKey: ["me"], queryFn: getCurrentUser, retry: false });
  const { locale, setLocale, t } = useI18n();
  const { theme, setTheme } = useThemePreference();
  const [profileOpen, setProfileOpen] = useState(false);

  useEffect(() => {
    if (userQuery.data) sessionStorage.setItem("user", JSON.stringify(userQuery.data));
  }, [userQuery.data]);

  useEffect(() => {
    if (userQuery.error) {
      sessionStorage.removeItem("user");
      window.location.href = "login.html";
    }
  }, [userQuery.error]);

  useEffect(() => {
    const user = userQuery.data;
    if (user && requireRole && !requireRole.includes(user.role)) {
      window.location.href = `access-denied.html?role=${encodeURIComponent(requireRole.join(" ou "))}`;
    }
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
                {t[item.labelKey as keyof typeof t]}
              </a>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <strong>{theme === "dark" ? t.themeDark : t.themeLight}</strong>
          <span>LabOnDemand</span>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <SearchBox placeholder="Rechercher un lab, volume ou template" />
          <div className="top-actions">
            <a className="icon-btn" href="documentation/README.md" title="Documentation">
              <BookOpen size={17} />
            </a>
            <IconButton
              title={theme === "dark" ? t.themeLight : t.themeDark}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </IconButton>
            <IconButton
              title={t.language}
              onClick={() => setLocale(locale === "fr" ? "en" : "fr")}
            >
              <Globe2 size={17} />
            </IconButton>
            <button className="user-chip user-chip-btn" id="username-display" onClick={() => setProfileOpen(true)}>
              <UserCircle size={18} />
              <span>
                {displayName(user)} · {roleLabel(user.role)}
              </span>
            </button>
            <IconButton
              id="logout-btn"
              title={t.logout}
              onClick={async () => {
                try {
                  await logout();
                } finally {
                  sessionStorage.removeItem("user");
                  window.location.href = "login.html";
                }
              }}
            >
              <LogOut size={17} />
            </IconButton>
          </div>
        </header>
        <div className="content">{children(user)}</div>
      </main>
      <ProfileDialog
        open={profileOpen}
        user={user}
        onOpenChange={setProfileOpen}
        onUpdated={(updated) => {
          queryClient.setQueryData(["me"], updated);
          sessionStorage.setItem("user", JSON.stringify(updated));
        }}
      />
    </div>
  );
}

function ProfileDialog({
  open,
  user,
  onOpenChange,
  onUpdated,
}: {
  open: boolean;
  user: Awaited<ReturnType<typeof getCurrentUser>>;
  onOpenChange: (open: boolean) => void;
  onUpdated: (user: Awaited<ReturnType<typeof getCurrentUser>>) => void;
}) {
  const { t } = useI18n();
  const [fullName, setFullName] = useState(user.full_name || "");
  const [email, setEmail] = useState(user.email || "");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  useEffect(() => {
    if (open) {
      setFullName(user.full_name || "");
      setEmail(user.email || "");
      setOldPassword("");
      setNewPassword("");
    }
  }, [open, user.email, user.full_name]);

  const profileMut = useMutation({
    mutationFn: () => updateProfile({ full_name: fullName, email }),
    onSuccess: (updated) => {
      onUpdated(updated);
      showToast("Profil mis a jour", "success");
    },
  });
  const passwordMut = useMutation({
    mutationFn: () => changePassword(oldPassword, newPassword),
    onSuccess: () => {
      setOldPassword("");
      setNewPassword("");
      showToast("Mot de passe modifie", "success");
    },
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{t.profileTitle}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          <div className="form-grid">
            <div className="field">
              <label htmlFor="profile-name">Nom complet</label>
              <input id="profile-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="profile-email">Email</label>
              <input id="profile-email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field full">
              <span className="badge">{roleLabel(user.role)}</span>
              {user.auth_provider === "oidc" ? <span className="muted">Compte gere par SSO.</span> : null}
            </div>
            {profileMut.error ? <ErrorState>{profileMut.error.message}</ErrorState> : null}
            <div className="actions-row field full justify-end">
              <Button onClick={() => profileMut.mutate()} disabled={profileMut.isPending} variant="primary">
                {profileMut.isPending ? "Enregistrement..." : t.save}
              </Button>
            </div>
          </div>

          {user.auth_provider !== "oidc" ? (
            <form
              className="form-grid mt-[18px] border-t border-[var(--border)] pt-[18px]"
              onSubmit={(e) => {
                e.preventDefault();
                passwordMut.mutate();
              }}
            >
              <h3 className="field full">{t.changePassword}</h3>
              <div className="field">
                <label htmlFor="old-password">Mot de passe actuel</label>
                <input id="old-password" type="password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="new-password">Nouveau mot de passe</label>
                <input id="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              {passwordMut.error ? <ErrorState>{passwordMut.error.message}</ErrorState> : null}
              <div className="actions-row field full justify-end">
                <Button type="submit" disabled={passwordMut.isPending || !oldPassword || !newPassword}>
                  {passwordMut.isPending ? "Modification..." : t.changePassword}
                </Button>
              </div>
            </form>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
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
