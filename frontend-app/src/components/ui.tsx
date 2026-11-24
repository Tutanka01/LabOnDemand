import * as Dialog from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as Tooltip from "@radix-ui/react-tooltip";
import * as SelectPrimitive from "@radix-ui/react-select";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import {
  type ButtonHTMLAttributes,
  type CSSProperties,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  useEffect,
  useState,
} from "react";
import { ApiError } from "../lib/api";
import { useI18n } from "../lib/i18n";

type ButtonVariant = "default" | "primary" | "danger" | "ghost";
type BadgeTone = "default" | "green" | "amber" | "red" | "blue";

export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function Button({
  variant = "default",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={cn("btn", variant !== "default" && variant, className)} {...props} />;
}

export function IconButton({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={cn("icon-btn", className)} {...props} />;
}

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props} />;
}

export function Panel({ className = "", ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={cn("panel", className)} {...props} />;
}

export function Badge({
  tone = "default",
  className = "",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return <span className={cn("badge", tone !== "default" && tone, className)} {...props} />;
}

export function ActionRow({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("actions-row", className)} {...props} />;
}

export function SearchBox(props: InputHTMLAttributes<HTMLInputElement>) {
  const { t } = useI18n();
  return (
    <label className="search">
      <Search size={17} aria-hidden="true" />
      <input aria-label={typeof props.placeholder === "string" ? props.placeholder : t("common.search")} {...props} />
    </label>
  );
}

export function MetricCard({ label, value, icon, hint }: { label: string; value: ReactNode; icon: ReactNode; hint?: string }) {
  return (
    <Card className="metric-card">
      <div className="metric-top">
        <span>{label}</span>
        {icon}
      </div>
      <strong className="metric-value">{value}</strong>
      {hint ? <span className="muted">{hint}</span> : null}
    </Card>
  );
}

export function StatusBadge({ state }: { state?: string | null }) {
  const { t } = useI18n();
  const value = (state || "unknown").toLowerCase();
  if (value === "running" || value === "active" || value === "ready") {
    return <Badge tone="green">{t("common.status_active")}</Badge>;
  }
  if (value === "paused") return <Badge tone="amber">{t("common.status_paused")}</Badge>;
  if (value === "starting" || value === "mixed" || value === "pending") {
    return <Badge tone="blue">{t("common.status_starting")}</Badge>;
  }
  if (value === "inactive" || value === "disabled") {
    return <Badge tone="amber">{t("common.status_inactive")}</Badge>;
  }
  if (value === "error" || value === "failed") return <Badge tone="red">{t("common.status_error")}</Badge>;
  if (value === "expired" || value === "deleted") return <Badge tone="red">{t("common.status_expired")}</Badge>;
  if (value === "archived") return <Badge tone="amber">{t("common.status_archived")}</Badge>;
  if (value === "ok" || value === "success") return <Badge tone="green">{t("common.status_ok")}</Badge>;
  if (value === "skipped") return <Badge tone="amber">{t("common.status_skipped")}</Badge>;
  if (value === "none") return <Badge>{t("common.status_none")}</Badge>;
  return <Badge>{t("common.status_unknown")}</Badge>;
}

export function ResourceMeter({ label, used, max, unit = "" }: { label: string; used?: number; max?: number; unit?: string }) {
  const percent = !max ? 0 : Math.max(0, Math.min(100, Math.round(((used || 0) / max) * 100)));
  const tone = percent >= 90 ? "danger" : percent >= 75 ? "warn" : "";
  return (
    <div className="resource-meter">
      <div className="meter-head">
        <span>{label}</span>
        <strong>
          {used ?? 0} / {max ?? 0} {unit}
        </strong>
      </div>
      <div className="meter-track" aria-hidden="true">
        <div className={`meter-fill ${tone}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children ? <span>{children}</span> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}

/** True when the API reported that Kubernetes could not be reached (HTTP 503). */
export function isClusterUnreachable(error: unknown): boolean {
  return error instanceof ApiError && error.status === 503;
}

/** Message to show for a failed request: the server `detail` when there is one, else `fallback`. */
export function errorMessage(error: unknown, fallback = ""): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

/**
 * Error panel. Pass `error` to show the server's message (and a "cluster unreachable"
 * title on HTTP 503) and `onRetry` to offer a retry button.
 */
export function ErrorState({
  title,
  children,
  error,
  onRetry,
  retrying = false,
}: {
  title?: string;
  children?: ReactNode;
  error?: unknown;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  const { t } = useI18n();
  const unreachable = isClusterUnreachable(error);
  const heading = unreachable ? t("common.cluster_unreachable") : title ?? t("common.error");
  const detail = error ? errorMessage(error) : "";
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={22} aria-hidden="true" />
      <strong>{heading}</strong>
      {children ? <span>{children}</span> : null}
      {detail && detail !== children ? <span className="text-xs">{detail}</span> : null}
      {unreachable ? <span className="muted text-xs">{t("common.cluster_unreachable_hint")}</span> : null}
      {onRetry ? (
        <Button onClick={onRetry} disabled={retrying}>
          <RefreshCw size={15} className={retrying ? "animate-spin" : undefined} aria-hidden="true" />
          {retrying ? t("common.retrying") : t("common.retry")}
        </Button>
      ) : null}
    </div>
  );
}

export function LoadingState({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="loading-state" role="status">
      <Loader2 size={22} className="animate-spin text-[var(--primary)]" aria-hidden="true" />
      <span>{label ?? t("common.loading")}</span>
    </div>
  );
}

type QueryLike = {
  data?: unknown;
  error: unknown;
  isLoading: boolean;
  isFetching?: boolean;
  refetch: () => unknown;
};

/**
 * Renders the loading / error / empty / content states of a TanStack query in one place.
 * A failed background refresh keeps showing the last data with an error banner above it.
 */
export function QueryState({
  query,
  skeleton,
  isEmpty = false,
  empty,
  errorTitle,
  children,
}: {
  query: QueryLike;
  skeleton?: ReactNode;
  isEmpty?: boolean;
  empty?: ReactNode;
  errorTitle?: string;
  children?: ReactNode;
}) {
  const retry = () => void query.refetch();
  if (query.isLoading) return <>{skeleton ?? <LoadingState />}</>;
  if (query.error && query.data === undefined) {
    return <ErrorState title={errorTitle} error={query.error} onRetry={retry} retrying={Boolean(query.isFetching)} />;
  }
  const banner = query.error ? (
    <ErrorState title={errorTitle} error={query.error} onRetry={retry} retrying={Boolean(query.isFetching)} />
  ) : null;
  return (
    <>
      {banner}
      {isEmpty ? empty : children}
    </>
  );
}

// ─── Skeletons ───────────────────────────────────────

export function Skeleton({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <div className={cn("skeleton", className)} style={style} aria-hidden="true" />;
}

/** Placeholder cards shown while a list loads. */
export function SkeletonCards({ count = 3, lines = 3 }: { count?: number; lines?: number }) {
  return (
    <div className="lab-list" aria-busy="true" aria-live="polite">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} className="lab-card">
          <div className="flex items-center justify-between gap-3">
            <Skeleton className="h-5 w-2/5" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
          {Array.from({ length: lines }).map((_, j) => (
            <Skeleton key={j} className="skeleton-text" style={{ width: `${88 - j * 16}%` }} />
          ))}
        </Card>
      ))}
    </div>
  );
}

/** Placeholder rows shown while a table loads. */
export function SkeletonRows({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="grid gap-2.5" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          {Array.from({ length: cols }).map((_, j) => (
            <Skeleton key={j} className="skeleton-text" style={{ flex: j === 0 ? 2 : 1 }} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function ConfirmDialog({
  title,
  description,
  trigger,
  confirmLabel,
  destructive = false,
  onConfirm,
}: {
  title: string;
  description: string;
  trigger: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const { t } = useI18n();
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{title}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label={t("common.close")}>
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">{description}</Dialog.Description>
          <ActionRow className="mt-4 justify-end">
            <Dialog.Close asChild>
              <Button>{t("common.cancel")}</Button>
            </Dialog.Close>
            <Dialog.Close asChild>
              <Button variant={destructive ? "danger" : "primary"} onClick={() => void onConfirm()}>
                {confirmLabel ?? t("common.confirm")}
              </Button>
            </Dialog.Close>
          </ActionRow>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ─── Tabs ────────────────────────────────────────────

export function Tabs({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  children: ReactNode;
}) {
  return (
    <TabsPrimitive.Root value={value} onValueChange={onChange}>
      {children}
    </TabsPrimitive.Root>
  );
}

export function TabList({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <TabsPrimitive.List className={cn("tab-list", className)}>{children}</TabsPrimitive.List>;
}

export function TabTrigger({ value, children }: { value: string; children: ReactNode }) {
  return (
    <TabsPrimitive.Trigger className="tab-trigger" value={value}>
      {children}
    </TabsPrimitive.Trigger>
  );
}

export function TabContent({ value, children }: { value: string; children: ReactNode }) {
  return <TabsPrimitive.Content className="tab-content" value={value}>{children}</TabsPrimitive.Content>;
}

// ─── Pagination ──────────────────────────────────────

export function Pagination({
  page,
  totalPages,
  onChange,
}: {
  page: number;
  totalPages: number;
  onChange: (p: number) => void;
}) {
  const { t } = useI18n();
  if (totalPages <= 1) return null;
  return (
    <div className="pagination">
      <Button disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <ChevronLeft size={16} aria-hidden="true" />
        <span className="sr-only">{t("common.previous_page")}</span>
      </Button>
      <span className="muted">
        {page} / {totalPages}
      </span>
      <Button disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
        <ChevronRight size={16} aria-hidden="true" />
        <span className="sr-only">{t("common.next_page")}</span>
      </Button>
    </div>
  );
}

// ─── Select ──────────────────────────────────────────

export function Select({
  label,
  value,
  onChange,
  options,
  placeholder,
  className = "",
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <div className={cn("select-root", className)}>
      {label ? <label className="select-label">{label}</label> : null}
      <SelectPrimitive.Root value={value} onValueChange={onChange}>
        <SelectPrimitive.Trigger className="select-trigger" aria-label={label}>
          <SelectPrimitive.Value placeholder={placeholder ?? t("common.select_placeholder")} />
          <SelectPrimitive.Icon>
            <ChevronDown size={14} />
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        <SelectPrimitive.Portal>
          <SelectPrimitive.Content className="select-content">
            <SelectPrimitive.Viewport>
              {options.map((opt) => (
                <SelectPrimitive.Item key={opt.value} value={opt.value} className="select-item">
                  <SelectPrimitive.ItemText>{opt.label}</SelectPrimitive.ItemText>
                </SelectPrimitive.Item>
              ))}
            </SelectPrimitive.Viewport>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
      </SelectPrimitive.Root>
    </div>
  );
}

// ─── Tooltip ─────────────────────────────────────────

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <Tooltip.Provider delayDuration={300}>{children}</Tooltip.Provider>;
}

export function TooltipWrapper({ content, children }: { content: string; children: ReactNode }) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tooltip-content" sideOffset={5}>
          {content}
          <Tooltip.Arrow className="tooltip-arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

// ─── Toast ───────────────────────────────────────────

interface ToastItem {
  id: number;
  message: string;
  type: "success" | "error" | "info";
}

let toastId = 0;
let toastSetter: ((updater: (prev: ToastItem[]) => ToastItem[]) => void) | null = null;

export function showToast(message: string, type: "success" | "error" | "info" = "info") {
  const id = ++toastId;
  if (toastSetter) {
    toastSetter((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      toastSetter?.((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    toastSetter = setToasts;
    return () => {
      toastSetter = null;
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-container" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={cn("toast", t.type)}>
          {t.type === "success" ? <Check size={16} /> : t.type === "error" ? <AlertTriangle size={16} /> : null}
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Form Field ──────────────────────────────────────

export function FormField({
  label,
  error,
  children,
  full,
  required,
}: {
  label: string;
  error?: string;
  children: ReactNode;
  full?: boolean;
  required?: boolean;
}) {
  return (
    <div className={cn("field", full && "full")}>
      <label>
        {label}
        {required ? <span className="required"> *</span> : null}
      </label>
      {children}
      {error ? <Badge tone="red">{error}</Badge> : null}
    </div>
  );
}

// ─── Modal Shell ─────────────────────────────────────

export function ModalShell({
  open,
  onOpenChange,
  title,
  children,
  wide,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const { t } = useI18n();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className={cn("dialog-content panel", wide && "dialog-wide")}
          aria-describedby={undefined}
        >
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{title}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label={t("common.close")}>
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
