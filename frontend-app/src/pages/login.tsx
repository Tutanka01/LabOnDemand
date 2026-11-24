import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2, Lock, ShieldCheck, User as UserIcon } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { AuthLayout, enter } from "../components/AuthLayout";
import { Button, ErrorState, LoadingState } from "../components/ui";
import { ApiError, getCurrentUser, getSsoStatus, login } from "../lib/api";
import { useI18n } from "../lib/i18n";

interface LoginForm {
  username: string;
  password: string;
}

/** Only same-origin, in-app paths are accepted as post-login targets (no open redirect). */
function safeNextPath(next: string | null): string {
  // Control characters and backslashes are stripped or rewritten by URL parsers
  // ("/\t/evil.com" becomes "//evil.com"), so reject them before resolving.
  if (!next || !next.startsWith("/") || /[\u0000-\u001f\\]/.test(next)) return "/";
  let target: URL;
  try {
    target = new URL(next, window.location.origin);
  } catch {
    return "/";
  }
  if (target.origin !== window.location.origin) return "/";
  if (target.pathname === "/login" || target.pathname.startsWith("/register")) return "/";
  return `${target.pathname}${target.search}${target.hash}`;
}

export default function LoginPage() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));

  // An existing session (e.g. after SSO or in another tab) skips the form.
  const session = useQuery({ queryKey: ["me"], queryFn: getCurrentUser, retry: false, refetchOnWindowFocus: false });
  const sso = useQuery({ queryKey: ["sso"], queryFn: getSsoStatus, staleTime: 5 * 60_000 });

  const form = useForm<LoginForm>({ defaultValues: { username: "", password: "" } });
  const { errors } = form.formState;

  const mutation = useMutation({
    mutationFn: (values: LoginForm) => login(values.username.trim(), values.password),
    onSuccess: (data) => {
      // Drop anything cached for a previous user, then seed the session so the
      // shell renders immediately; the redirect below follows from `session.data`.
      queryClient.clear();
      queryClient.setQueryData(["me"], data.user);
    },
    onError: () => {
      form.resetField("password");
      form.setFocus("password");
    },
  });

  if (session.data) {
    return <Navigate to={nextPath} replace />;
  }
  if (mutation.isSuccess) {
    return <LoadingState label={t("auth.redirecting")} />;
  }

  const errorMessage = mutation.error ? loginErrorMessage(mutation.error, t) : null;
  const pending = mutation.isPending;

  return (
    <AuthLayout
      title={t("auth.tagline")}
      lead={t("auth.tagline_sub")}
      features={[t("auth.feature_templates"), t("auth.feature_volumes"), t("auth.feature_realtime")]}
    >
      <form
        className="card auth-card"
        noValidate
        aria-busy={pending}
        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
      >
        <div {...enter(0)}>
          <div className="grid gap-1.5">
            <h1>{t("login.title")}</h1>
            <p className="sub">{sso.data ? t("login.info_sso") : t("login.info")}</p>
          </div>
        </div>

        {errorMessage ? <ErrorState title={t("login.error")}>{errorMessage}</ErrorState> : null}

        <div {...enter(1)}>
          <div className="field">
            <label htmlFor="username">
              <span className="inline-flex items-center gap-2">
                <UserIcon size={15} className="text-[var(--muted)]" aria-hidden="true" /> {t("login.username")}
              </span>
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              autoFocus
              placeholder={t("auth.username_placeholder")}
              aria-invalid={errors.username ? true : undefined}
              aria-describedby={errors.username ? "username-error" : undefined}
              {...form.register("username", {
                validate: (value) => value.trim().length > 0 || t("auth.username_required"),
              })}
            />
            {errors.username ? (
              <span id="username-error" className="field-error">
                {errors.username.message}
              </span>
            ) : null}
          </div>
        </div>

        <div {...enter(2)}>
          <div className="field">
            <label htmlFor="password">
              <span className="inline-flex items-center gap-2">
                <Lock size={15} className="text-[var(--muted)]" aria-hidden="true" /> {t("login.password")}
              </span>
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              aria-invalid={errors.password ? true : undefined}
              aria-describedby={errors.password ? "password-error" : undefined}
              {...form.register("password", { required: t("auth.password_required") })}
            />
            {errors.password ? (
              <span id="password-error" className="field-error">
                {errors.password.message}
              </span>
            ) : null}
          </div>
        </div>

        <div {...enter(3)}>
          <Button className="w-full justify-center" variant="primary" type="submit" disabled={pending}>
            {pending ? (
              <>
                <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                {t("auth.signing_in")}
              </>
            ) : (
              <>
                {t("login.submit")}
                <ArrowRight size={16} aria-hidden="true" />
              </>
            )}
          </Button>
        </div>

        {sso.data ? (
          <div {...enter(4)}>
            <div className="grid gap-4">
              <div className="flex items-center gap-3 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
                <span className="hairline h-px flex-1" />
                {t("common.or")}
                <span className="hairline h-px flex-1" />
              </div>
              <Button className="w-full justify-center" type="button" onClick={() => (window.location.href = "/api/v1/auth/sso/login")}>
                <ShieldCheck size={16} aria-hidden="true" />
                {t("login.sso_continue")}
              </Button>
            </div>
          </div>
        ) : (
          <p {...enter(4, "muted text-center")}>
            {t("auth.no_account")}{" "}
            <Link className="font-bold text-[var(--primary)] hover:underline" to="/register">
              {t("auth.register_link")}
            </Link>
          </p>
        )}
      </form>
    </AuthLayout>
  );
}

function loginErrorMessage(error: Error, t: (key: string) => string): string {
  if (!(error instanceof ApiError)) return t("auth.network_error");
  if (error.status === 401) return t("auth.invalid_credentials");
  if (error.status === 429) return t("auth.too_many_attempts");
  if (error.status >= 500) return t("auth.server_unavailable");
  // 403 and other refusals carry an explicit reason (disabled account, SSO-only account...).
  return error.message;
}
