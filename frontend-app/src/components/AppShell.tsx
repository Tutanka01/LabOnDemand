import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpen,
  Boxes,
  Globe2,
  LayoutDashboard,
  LogOut,
  Moon,
  Shield,
  Sun,
  Users,
  X,
} from "lucide-react";
import { useState, useEffect, ReactNode, type FormEvent } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { changePassword, CSRF_HEADERS, getCurrentUser, logout, pingK8s, updateProfile } from "../lib/api";
import { displayName, initials, roleLabel } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { RuntimeIcon } from "../lib/icons";
import { useThemePreference } from "../lib/theme";
import { Button, ErrorState, IconButton, LoadingState, SearchBox, showToast, ToastContainer } from "./ui";

const nav = [
  { to: "/", labelKey: "header.home", icon: LayoutDashboard, roles: ["student", "teacher", "admin"] },
  { to: "/labs", labelKey: "header.catalog", icon: Boxes, roles: ["student"] },
  { to: "/teacher", labelKey: "header.my_classes", icon: Users, roles: ["teacher", "admin"] },
  { to: "/admin", labelKey: "header.admin", icon: Shield, roles: ["admin"] },
  { to: "/admin-stats", labelKey: "header.stats", icon: BarChart3, roles: ["admin"] },
];

const documentationHref = "documentation.html";

function normalizeSearch(value: string) {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

export function AppShellLayout({
  requireRole,
}: {
  requireRole?: Array<"admin" | "teacher" | "student">;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();

  const userQuery = useQuery({ queryKey: ["me"], queryFn: getCurrentUser, retry: false });
  const { locale, setLocale, t } = useI18n();
  const { theme, setTheme } = useThemePreference();
  const [profileOpen, setProfileOpen] = useState(false);
  const [quickNav, setQuickNav] = useState("");

  // Status check (API and Kubernetes status dot)
  const apiStatus = useQuery({
    queryKey: ["status-api"],
    queryFn: async () => {
      try {
        const res = await fetch("/api/v1/status", { headers: CSRF_HEADERS });
        return res.ok;
      } catch {
        return false;
      }
    },
    refetchInterval: 30_000,
  });

  const k8sStatus = useQuery({
    queryKey: ["status-k8s"],
    queryFn: pingK8s,
    refetchInterval: 30_000,
  });

  useEffect(() => {
    if (userQuery.data) sessionStorage.setItem("user", JSON.stringify(userQuery.data));
  }, [userQuery.data]);

  useEffect(() => {
    if (userQuery.error) {
      sessionStorage.removeItem("user");
      navigate("/login");
    }
  }, [userQuery.error, navigate]);

  useEffect(() => {
    const user = userQuery.data;
    if (user && requireRole && !requireRole.includes(user.role)) {
      const roleSeparator = locale === "fr" ? " ou " : " or ";
      navigate(`/access-denied?role=${encodeURIComponent(requireRole.map((role) => roleLabel(role, locale)).join(roleSeparator))}`);
    }
  }, [locale, requireRole, userQuery.data, navigate]);

  if (!userQuery.data) return <LoadingState label={locale === "fr" ? "Vérification de la session" : "Checking session"} />;

  const user = userQuery.data;
  const allowedNav = nav.filter((item) => item.roles.includes(user.role));

  const handleQuickNav = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = normalizeSearch(quickNav);
    if (!query) return;

    const target = allowedNav.find((item) => {
      const label = normalizeSearch(`${t(item.labelKey)} ${item.to}`);
      return label.includes(query) || query.includes(label);
    });

    if (target) {
      setQuickNav("");
      navigate(target.to);
      return;
    }

    if (query.includes("doc") || query.includes("aide") || query.includes("help")) {
      window.open(documentationHref, "_blank", "noopener,noreferrer");
      setQuickNav("");
      return;
    }

    showToast(
      locale === "fr" ? "Aucune page ne correspond à cette recherche." : "No page matches this search.",
      "info",
    );
  };

  // Connection status info
  let statusText = t("header.status_ok");
  let statusColor = "var(--success)";

  if (!apiStatus.data) {
    statusText = t("header.status_api_down");
    statusColor = "var(--danger)";
  } else if (!k8sStatus.data) {
    statusText = t("header.status_k8s_down");
    statusColor = "var(--warning)";
  }

  const isDark = theme === "dark";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <span className="brand-mark">
            <RuntimeIcon type="flask" />
          </span>
          <span>LabOnDemand</span>
        </Link>
        <nav className="nav" aria-label="Navigation principale">
          {allowedNav.map((item) => {
            const Icon = item.icon;
            const active = location.pathname === item.to;
            return (
              <Link className={active ? "active" : ""} to={item.to} key={item.to} aria-current={active ? "page" : undefined}>
                <Icon size={16} />
                {t(item.labelKey)}
              </Link>
            );
          })}
        </nav>
      </aside>

      <main className="main flex min-h-screen flex-col">
        <header className="topbar">
          <div className="flex min-w-0 items-center gap-3">
            <form className="quick-nav-form" onSubmit={handleQuickNav}>
              <SearchBox
                placeholder={t("header.quick_nav")}
                value={quickNav}
                onChange={(event) => setQuickNav(event.target.value)}
              />
            </form>

            <div className="status-pill" title={statusText}>
              <span
                className="h-2 w-2 flex-none rounded-full"
                style={{ background: statusColor }}
                aria-hidden="true"
              />
              <span>{statusText}</span>
            </div>
          </div>

          <div className="top-actions">
            <a className="icon-btn" href={documentationHref} target="_blank" rel="noreferrer" title="Documentation" aria-label="Documentation">
              <BookOpen size={16} />
            </a>
            <IconButton
              title={isDark ? (locale === "fr" ? "Activer le mode clair" : "Switch to light mode") : (locale === "fr" ? "Activer le mode sombre" : "Switch to dark mode")}
              aria-label={isDark ? (locale === "fr" ? "Activer le mode clair" : "Switch to light mode") : (locale === "fr" ? "Activer le mode sombre" : "Switch to dark mode")}
              onClick={() => setTheme(isDark ? "light" : "dark")}
            >
              {isDark ? <Sun size={16} /> : <Moon size={16} />}
            </IconButton>
            <IconButton
              title={locale === "fr" ? "Switch to English" : "Passer en Français"}
              aria-label={locale === "fr" ? "Switch to English" : "Passer en Français"}
              onClick={() => setLocale(locale === "fr" ? "en" : "fr")}
            >
              <Globe2 size={16} />
            </IconButton>
            <button className="user-chip user-chip-btn" id="username-display" onClick={() => setProfileOpen(true)}>
              <span
                className="grid h-7 w-7 flex-none place-items-center rounded-full text-[var(--text-xs)] font-semibold"
                style={{ background: "var(--primary)", color: "var(--primary-text)" }}
                aria-hidden="true"
              >
                {initials(user)}
              </span>
              <span className="hidden flex-col items-start leading-tight sm:flex">
                <strong className="text-[var(--text-xs)] font-semibold text-[var(--text)]">{displayName(user)}</strong>
                <span className="text-[var(--text-xs)]">{roleLabel(user.role, locale)}</span>
              </span>
            </button>
            <IconButton
              id="logout-btn"
              title={t("header.logout")}
              aria-label={t("header.logout")}
              onClick={async () => {
                try {
                  await logout();
                } finally {
                  sessionStorage.removeItem("user");
                  navigate("/login");
                }
              }}
            >
              <LogOut size={16} />
            </IconButton>
          </div>
        </header>

        <div className="content flex-1">
          <div className="flex w-full flex-col gap-6">
            <Outlet context={user} />
          </div>
        </div>
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
      <ToastContainer />
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
  const { locale, t } = useI18n();
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
      showToast(locale === "fr" ? "Profil mis à jour" : "Profile updated", "success");
    },
  });
  const passwordMut = useMutation({
    mutationFn: () => changePassword(oldPassword, newPassword),
    onSuccess: () => {
      setOldPassword("");
      setNewPassword("");
      showToast(locale === "fr" ? "Mot de passe modifié" : "Password changed", "success");
    },
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel" aria-describedby={undefined}>
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{t("profileTitle") || "Mon profil"}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          <div className="form-grid">
            <div className="field">
              <label htmlFor="profile-name">{locale === "fr" ? "Nom complet" : "Full name"}</label>
              <input id="profile-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="profile-email">Email</label>
              <input id="profile-email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field full">
              <span className="badge">{roleLabel(user.role, locale)}</span>
              {user.auth_provider === "oidc" ? <span className="muted">{locale === "fr" ? "Compte géré par SSO." : "Account managed by SSO."}</span> : null}
            </div>
            {profileMut.error ? <ErrorState>{profileMut.error.message}</ErrorState> : null}
            <div className="actions-row field full justify-end">
              <Button onClick={() => profileMut.mutate()} disabled={profileMut.isPending} variant="primary">
                {profileMut.isPending ? (locale === "fr" ? "Enregistrement..." : "Saving...") : (t("common.save") || "Enregistrer")}
              </Button>
            </div>
          </div>

          {user.auth_provider !== "oidc" ? (
            <form
              className="form-grid mt-4 border-t border-[var(--border)] pt-4"
              onSubmit={(e) => {
                e.preventDefault();
                passwordMut.mutate();
              }}
            >
              <h3 className="field full">{t("changePassword") || "Changer le mot de passe"}</h3>
              <div className="field">
                <label htmlFor="old-password">{locale === "fr" ? "Mot de passe actuel" : "Current password"}</label>
                <input id="old-password" type="password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="new-password">{locale === "fr" ? "Nouveau mot de passe" : "New password"}</label>
                <input id="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              {passwordMut.error ? <ErrorState>{passwordMut.error.message}</ErrorState> : null}
              <div className="actions-row field full justify-end">
                <Button type="submit" disabled={passwordMut.isPending || !oldPassword || !newPassword}>
                  {passwordMut.isPending ? (locale === "fr" ? "Modification..." : "Changing...") : (t("changePassword") || "Changer le mot de passe")}
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
