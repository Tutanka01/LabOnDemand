import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useI18n } from "../lib/i18n";

/**
 * Suspense fallback for lazily loaded routes. Renders nothing for the first
 * `delayMs` so fast chunk loads do not flash a spinner. Deliberately does not
 * import components/ui.tsx, which would pull Radix into the entry chunk.
 */
export function RouteFallback({ delayMs = 250 }: { delayMs?: number }) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const id = window.setTimeout(() => setVisible(true), delayMs);
    return () => window.clearTimeout(id);
  }, [delayMs]);

  if (!visible) return null;
  return (
    <div className="loading-state" role="status">
      <Loader2 size={22} className="animate-spin text-[var(--primary)]" aria-hidden="true" />
      <span>{t("common.loading")}</span>
    </div>
  );
}
