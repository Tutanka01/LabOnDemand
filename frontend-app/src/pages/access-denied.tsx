import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, LogIn, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { enter } from "../components/AuthLayout";
import { Button } from "../components/ui";
import { logout } from "../lib/api";
import { useI18n } from "../lib/i18n";

const REDIRECT_SECONDS = 8;

export default function AccessDeniedPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const requiredRole = searchParams.get("role");
  const [countdown, setCountdown] = useState(REDIRECT_SECONDS);
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    if (switching) return;
    const timer = window.setInterval(() => setCountdown((value) => Math.max(value - 1, 0)), 1000);
    return () => window.clearInterval(timer);
  }, [switching]);

  useEffect(() => {
    if (countdown === 0) navigate("/", { replace: true });
  }, [countdown, navigate]);

  // The login page skips the form while a session exists, so switching
  // account means ending the current session first.
  const switchAccount = async () => {
    setSwitching(true);
    try {
      await logout();
    } catch {
      // Session already gone or API unreachable: the login page will tell.
    }
    queryClient.clear();
    navigate("/login", { replace: true });
  };

  return (
    <main className="grid min-h-screen place-items-center p-6">
      <section {...enter(0, "card auth-card text-center", { boxShadow: "var(--shadow-lg)" })}>
        <div
          {...enter(1, "mx-auto grid h-14 w-14 place-items-center rounded-[var(--radius)]", {
            background: "color-mix(in srgb, var(--danger) 10%, var(--surface))",
          })}
        >
          <ShieldAlert size={26} className="text-[var(--danger)]" aria-hidden="true" />
        </div>

        <div {...enter(2)}>
          <div className="grid gap-2">
            <h1>{t("error.forbidden")}</h1>
            <p className="sub mx-auto max-w-[340px]">{t("auth.denied.body")}</p>
            {requiredRole ? (
              <span className="badge mx-auto">{t("auth.denied.required_role", { role: requiredRole })}</span>
            ) : null}
          </div>
        </div>

        <div {...enter(3)}>
          <div className="grid gap-2">
            <Button id="back-to-home" className="w-full justify-center" variant="primary" onClick={() => navigate("/", { replace: true })}>
              <ArrowLeft size={16} aria-hidden="true" />
              {t("auth.denied.back")}
            </Button>
            <Button className="w-full justify-center" onClick={switchAccount} disabled={switching}>
              <LogIn size={16} aria-hidden="true" />
              {t("auth.denied.switch_account")}
            </Button>
          </div>
        </div>

        {switching ? null : (
          <span {...enter(4, "muted text-xs")}>
            {t("auth.denied.redirecting", { seconds: countdown })}
          </span>
        )}
      </section>
    </main>
  );
}
