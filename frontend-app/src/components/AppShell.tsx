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
import { Suspense, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { apiFetch, changePassword, getCurrentUser, logout, updateProfile } from "../lib/api";
import { displayName, initials, roleLabel } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { RuntimeIcon } from "../lib/icons";
import { isAuthError, isClientError } from "../lib/query";
import { useThemePreference } from "../lib/theme";
import type { Role, User } from "../types/api";
import { ErrorBoundary } from "./ErrorBoundary";
import { RouteFallback } from "./RouteFallback";
import { Button, ErrorState, IconButton, SearchBox, showToast, ToastContainer, TooltipProvider } from "./ui";

const nav: Array<{ to: string; labelKey: string; icon: typeof LayoutDashboard; roles: Role[] }> = [
  { to: "/", labelKey: "header.home", icon: LayoutDashboard, roles: ["student", "teacher", "admin"] },
  { to: "/labs", labelKey: "header.catalog", icon: Boxes, roles: ["student"] },
  { to: "/teacher", labelKey: "header.my_classes", icon: Users, roles: ["teacher", "admin"] },
  { to: "/admin", labelKey: "header.admin", icon: Shield, roles: ["admin"] },
  { to: "/admin-stats", labelKey: "header.stats", icon: BarChart3, roles: ["admin"] },
];

const documentationHref = "/documentation.html";
const STATUS_POLL_MS = 30_000;
const SESSION_RETRY_MS = 5_000;

function normalizeSearch(value: string) {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim();
}

export function AppShellLayout({ requireRole }: { requireRole?: Role[] }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const { locale, setLocale, t } = useI18n();
  const { theme, setTheme } = useThemePreference();
  const [profileOpen, setProfileOpen] = useState(false);
  const [quickNav, setQuickNav] = useState("");

  const userQuery = useQuery({
    queryKey: ["me"],
    queryFn: getCurrentUser,
    staleTime: 5 * 60_000,
    // Auth refusals are final; network errors and 5xx keep being retried
    // until the API is back, without ever logging the user out.
    retry: (failureCount, error) => !isClientError(error) && failureCount < 2,
    refetchInterval: (query) =>
      query.state.status === "error" && !isAuthError(query.state.error) ? SESSION_RETRY_MS : false,
  });
  const user = userQuery.data;

  // One lightweight probe drives the status pill: it answers only if the API
  // is up, and its payload says whether Kubernetes is reachable. TanStack Query
  // pauses refetchInterval while the tab is hidden.
  const statusQuery = useQuery({
    queryKey: ["shell-status"],
    queryFn: () => apiFetch<{ k8s?: boolean }>("/api/v1/k8s/ping"),
    enabled: Boolean(user),
    refetchInterval: STATUS_POLL_MS,
    staleTime: STATUS_POLL_MS,
    retry: false,
  });

  const sessionLost = isAuthError(userQuery.error);
  useEffect(() => {
    if (!sessionLost) return;
    queryClient.clear();
    const next = `${location.pathname}${location.search}`;
    navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
    // Only react to the session being lost, not to later location changes.
  }, [sessionLost]);

  if (!user) {
    if (userQuery.isError && !sessionLost) {
      return <ServiceUnavailable retrying={userQuery.isFetching} onRetry={() => void userQuery.refetch()} />;
    }
    return <RouteFallback />;
  }

  if (requireRole && !requireRole.includes(user.role)) {
    const roles = requireRole.map((role) => roleLabel(role, locale)).join(` ${t("common.or")} `);
    return <Navigate to={`/access-denied?role=${encodeURIComponent(roles)}`} replace />;
  }

  const allowedNav = nav.filter((item) => item.roles.includes(user.role));

  const handleQuickNav = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const query = normalizeSearch(quickNav);
    if (!query) return;

    const target = allowedNav.find((item) => normalizeSearch(`${t(item.labelKey)} ${item.to}`).includes(query));
    if (target) {
      setQuickNav("");
      navigate(target.to);
      return;
    }

    const docTerms = normalizeSearch(`${t("shell.documentation")} doc help aide`);
    if (docTerms.includes(query) || query.includes("doc")) {
      setQuickNav("");
      window.open(documentationHref, "_blank", "noopener,noreferrer");
      return;
    }

    showToast(t("shell.quick_nav_no_match"), "info");
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      showToast(t("shell.logout_failed"), "error");
      return;
    }
    navigate("/login", { replace: true });
    queryClient.clear();
  };

  let statusText = t("shell.status_checking");
  let statusColor = "var(--muted)";
  if (statusQuery.isError && !isClientError(statusQuery.error)) {
    statusText = t("header.status_api_down");
    statusColor = "var(--danger)";
  } else if (statusQuery.data?.k8s === false) {
    statusText = t("header.status_k8s_down");
    statusColor = "var(--warning)";
  } else if (statusQuery.data?.k8s) {
    statusText = t("header.status_ok");
    statusColor = "var(--success)";
  }

  const isDark = theme === "dark";
  const otherLocale = locale === "en" ? "fr" : "en";
  const themeLabel = isDark ? t("shell.theme_to_light") : t("shell.theme_to_dark");

  return (
    // Radix requires a Provider above every Tooltip.Root used by the pages.
    <TooltipProvider>
      <div className="app-shell">
        <aside className="sidebar">
          <Link className="brand" to="/">
            <span className="brand-mark">
              <RuntimeIcon type="flask" />
            </span>
            <span>LabOnDemand</span>
          </Link>
          <nav className="nav" aria-label={t("shell.nav_label")}>
            {allowedNav.map((item) => {
              const Icon = item.icon;
              const active = location.pathname === item.to || (item.to !== "/" && location.pathname.startsWith(`${item.to}/`));
              return (
                <Link className={active ? "active" : ""} to={item.to} key={item.to} aria-current={active ? "page" : undefined}>
                  <Icon size={16} aria-hidden="true" />
                  {t(item.labelKey)}
                </Link>
              );
            })}
          </nav>
        </aside>

        <main className="main flex min-h-screen flex-col">
          <header className="topbar">
            <div className="flex min-w-0 items-center gap-3">
              <form className="quick-nav-form" role="search" onSubmit={handleQuickNav}>
                <SearchBox
                  placeholder={t("header.quick_nav")}
                  value={quickNav}
                  onChange={(event) => setQuickNav(event.target.value)}
                />
              </form>

              <div className="status-pill" title={statusText} role="status">
                <span className="h-2 w-2 flex-none rounded-full" style={{ background: statusColor }} aria-hidden="true" />
                <span>{statusText}</span>
              </div>
            </div>

            <div className="top-actions">
              <a
                className="icon-btn"
                href={documentationHref}
                target="_blank"
                rel="noreferrer"
                title={t("shell.documentation")}
                aria-label={t("shell.documentation")}
              >
                <BookOpen size={16} aria-hidden="true" />
              </a>
              <IconButton title={themeLabel} aria-label={themeLabel} onClick={() => setTheme(isDark ? "light" : "dark")}>
                {isDark ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
              </IconButton>
              <IconButton
                title={t("shell.switch_language")}
                aria-label={t("shell.switch_language")}
                lang={otherLocale}
                onClick={() => setLocale(otherLocale)}
              >
                <Globe2 size={16} aria-hidden="true" />
              </IconButton>
              <button
                className="user-chip user-chip-btn"
                id="username-display"
                type="button"
                title={t("shell.open_profile")}
                onClick={() => setProfileOpen(true)}
              >
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
                <span className="sr-only sm:hidden">{displayName(user)}</span>
              </button>
              <IconButton id="logout-btn" title={t("header.logout")} aria-label={t("header.logout")} onClick={handleLogout}>
                <LogOut size={16} aria-hidden="true" />
              </IconButton>
            </div>
          </header>

          <div className="content flex-1">
            <div className="flex w-full flex-col gap-6">
              <ErrorBoundary resetKey={location.pathname}>
                <Suspense fallback={<RouteFallback />}>
                  <Outlet context={user} />
                </Suspense>
              </ErrorBoundary>
            </div>
          </div>
        </main>

        <ProfileDialog
          open={profileOpen}
          user={user}
          onOpenChange={setProfileOpen}
          onUpdated={(updated) => queryClient.setQueryData(["me"], updated)}
        />
        <ToastContainer />
      </div>
    </TooltipProvider>
  );
}

/** Shown instead of the app while /auth/me fails for a reason other than authentication. */
function ServiceUnavailable({ retrying, onRetry }: { retrying: boolean; onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <div className="max-w-md">
        <ErrorState title={t("shell.unavailable.title")} onRetry={onRetry} retrying={retrying}>
          {t("shell.unavailable.body")}
        </ErrorState>
      </div>
    </main>
  );
}

function ProfileDialog({
  open,
  user,
  onOpenChange,
  onUpdated,
}: {
  open: boolean;
  user: User;
  onOpenChange: (open: boolean) => void;
  onUpdated: (user: User) => void;
}) {
  const { locale, t } = useI18n();
  const [fullName, setFullName] = useState(user.full_name || "");
  const [email, setEmail] = useState(user.email || "");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const profileMut = useMutation({
    mutationFn: () => updateProfile({ full_name: fullName, email }),
    onSuccess: (updated) => {
      onUpdated(updated);
      showToast(t("shell.profile.updated"), "success");
    },
  });
  const passwordMut = useMutation({
    mutationFn: () => changePassword(oldPassword, newPassword),
    onSuccess: () => {
      setOldPassword("");
      setNewPassword("");
      showToast(t("shell.profile.password_changed"), "success");
    },
  });

  // Start from the current profile each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    setFullName(user.full_name || "");
    setEmail(user.email || "");
    setOldPassword("");
    setNewPassword("");
    profileMut.reset();
    passwordMut.reset();
  }, [open, user.email, user.full_name]);

  const isSso = user.auth_provider === "oidc";

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel" aria-describedby={undefined}>
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{t("profileTitle")}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label={t("common.close")} title={t("common.close")}>
                <X size={17} aria-hidden="true" />
              </IconButton>
            </Dialog.Close>
          </div>

          <form
            className="form-grid"
            onSubmit={(e) => {
              e.preventDefault();
              profileMut.mutate();
            }}
          >
            <div className="field">
              <label htmlFor="profile-name">{t("shell.profile.full_name")}</label>
              <input id="profile-name" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="profile-email">{t("shell.profile.email")}</label>
              <input id="profile-email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field full">
              <span className="badge">{roleLabel(user.role, locale)}</span>
              {isSso ? <span className="muted">{t("shell.profile.sso_managed")}</span> : null}
            </div>
            {profileMut.error ? <ErrorState title={t("common.error")}>{profileMut.error.message}</ErrorState> : null}
            <div className="actions-row field full justify-end">
              <Button type="submit" disabled={profileMut.isPending} variant="primary">
                {profileMut.isPending ? t("shell.profile.saving") : t("common.save")}
              </Button>
            </div>
          </form>

          {isSso ? null : (
            <form
              className="form-grid mt-4 border-t border-[var(--border)] pt-4"
              onSubmit={(e) => {
                e.preventDefault();
                passwordMut.mutate();
              }}
            >
              <h3 className="field full">{t("changePassword")}</h3>
              {/* Lets password managers associate the new password with this account. */}
              <input type="text" className="sr-only" autoComplete="username" value={user.username} readOnly tabIndex={-1} aria-hidden="true" />
              <div className="field">
                <label htmlFor="old-password">{t("shell.profile.current_password")}</label>
                <input
                  id="old-password"
                  type="password"
                  autoComplete="current-password"
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="new-password">{t("shell.profile.new_password")}</label>
                <input
                  id="new-password"
                  type="password"
                  autoComplete="new-password"
                  aria-describedby="new-password-hint"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                />
              </div>
              <p id="new-password-hint" className="field full muted text-[var(--text-xs)]">
                {t("shell.profile.password_hint")}
              </p>
              {passwordMut.error ? <ErrorState title={t("common.error")}>{passwordMut.error.message}</ErrorState> : null}
              <div className="actions-row field full justify-end">
                <Button type="submit" disabled={passwordMut.isPending || !oldPassword || !newPassword}>
                  {passwordMut.isPending ? t("shell.profile.changing_password") : t("changePassword")}
                </Button>
              </div>
            </form>
          )}
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
