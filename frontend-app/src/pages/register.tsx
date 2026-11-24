import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ShieldCheck, UserPlus } from "lucide-react";
import { Link } from "react-router-dom";
import { AuthLayout, enter } from "../components/AuthLayout";
import { Button } from "../components/ui";
import { getSsoStatus } from "../lib/api";
import { useI18n } from "../lib/i18n";

/** Self-registration is disabled: accounts come from an administrator or from SSO. */
export default function RegisterPage() {
  const { t } = useI18n();
  const sso = useQuery({ queryKey: ["sso"], queryFn: getSsoStatus, staleTime: 5 * 60_000 });

  return (
    <AuthLayout
      title={t("register.title")}
      lead={t("auth.register.lead")}
      features={[t("auth.register.feature_roles"), t("auth.register.feature_sso"), t("auth.register.feature_local")]}
    >
      <div className="card auth-card text-center">
        <div
          {...enter(0, "mx-auto grid h-14 w-14 place-items-center rounded-[var(--radius)]", {
            background: "var(--primary)",
            color: "var(--primary-text)",
          })}
        >
          <UserPlus size={24} aria-hidden="true" />
        </div>

        <div {...enter(1)}>
          <div className="grid gap-1.5">
            <h1>{t("auth.register.unavailable_title")}</h1>
            <p className="sub">{t("auth.register.unavailable_body")}</p>
          </div>
        </div>

        {sso.data ? (
          <div {...enter(2)}>
            <Button
              className="w-full justify-center"
              variant="primary"
              type="button"
              onClick={() => (window.location.href = "/api/v1/auth/sso/login")}
            >
              <ShieldCheck size={16} aria-hidden="true" />
              {t("login.sso_continue")}
            </Button>
          </div>
        ) : null}

        <div {...enter(3)}>
          <div className="grid gap-2.5">
            <Link to="/admin" className="btn w-full justify-center">
              <UserPlus size={16} aria-hidden="true" />
              {t("auth.register.admin_space")}
            </Link>
            <Link to="/login" className="btn w-full justify-center">
              {t("login.submit")}
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>
        </div>
      </div>
    </AuthLayout>
  );
}
