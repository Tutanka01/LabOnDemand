import * as Dialog from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as Tooltip from "@radix-ui/react-tooltip";
import * as SelectPrimitive from "@radix-ui/react-select";
import { AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, Loader2, Search, X } from "lucide-react";
import {
  type ButtonHTMLAttributes,
  type CSSProperties,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
  useEffect,
  useState,
} from "react";
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

export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={className} {...props} />;
}

export function Textarea({ className = "", ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={className} {...props} />;
}

export function ActionRow({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("actions-row", className)} {...props} />;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <h1>{title}</h1>
        {description ? <p className="sub">{description}</p> : null}
      </div>
      {actions ? <ActionRow>{actions}</ActionRow> : null}
    </div>
  );
}

export function SearchBox(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="search">
      <Search size={17} />
      <input aria-label={typeof props.placeholder === "string" ? props.placeholder : "Search"} {...props} />
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
  const { locale } = useI18n();
  const value = (state || "unknown").toLowerCase();
  if (value === "running" || value === "active" || value === "ready") {
    return <Badge tone="green">{locale === "fr" ? "Actif" : "Active"}</Badge>;
  }
  if (value === "paused") return <Badge tone="amber">{locale === "fr" ? "En pause" : "Paused"}</Badge>;
  if (value === "starting" || value === "mixed" || value === "pending") {
    return <Badge tone="blue">{locale === "fr" ? "Initialisation" : "Starting"}</Badge>;
  }
  if (value === "inactive" || value === "disabled") {
    return <Badge tone="amber">{locale === "fr" ? "Inactif" : "Inactive"}</Badge>;
  }
  if (value === "error" || value === "failed") return <Badge tone="red">{locale === "fr" ? "Erreur" : "Error"}</Badge>;
  if (value === "expired" || value === "deleted") return <Badge tone="red">{locale === "fr" ? "Expiré" : "Expired"}</Badge>;
  if (value === "archived") return <Badge tone="amber">{locale === "fr" ? "Archivé" : "Archived"}</Badge>;
  if (value === "ok" || value === "success") return <Badge tone="green">{locale === "fr" ? "OK" : "OK"}</Badge>;
  if (value === "none") return <Badge>{locale === "fr" ? "Aucun" : "None"}</Badge>;
  return <Badge>{locale === "fr" ? "Inconnu" : "Unknown"}</Badge>;
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

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children ? <span>{children}</span> : null}
    </div>
  );
}

export function ErrorState({ title = "Erreur", children }: { title?: string; children?: ReactNode }) {
  return (
    <div className="error-state">
      <AlertTriangle size={22} />
      <strong>{title}</strong>
      {children ? <span>{children}</span> : null}
    </div>
  );
}

export function LoadingState({ label = "Chargement" }: { label?: string }) {
  return (
    <div className="loading-state">
      <Loader2 size={22} className="animate-spin text-[var(--primary)]" />
      <span>{label}</span>
    </div>
  );
}

// ─── Skeletons (shimmer) ─────────────────────────────

export function Skeleton({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <div className={cn("skeleton", className)} style={style} aria-hidden="true" />;
}

/** Grille de cartes fantômes pour les états de chargement de listes. */
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

/** Rangées fantômes pour les tableaux. */
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
  confirmLabel = "Confirmer",
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
              <IconButton aria-label="Fermer">
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>
          <Dialog.Description className="muted">{description}</Dialog.Description>
          <ActionRow className="mt-[18px] justify-end">
            <Dialog.Close asChild>
              <Button>{t("common.cancel")}</Button>
            </Dialog.Close>
            <Dialog.Close asChild>
              <Button variant={destructive ? "danger" : "primary"} onClick={() => void onConfirm()}>
                {confirmLabel}
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
  if (totalPages <= 1) return null;
  return (
    <div className="pagination">
      <Button disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <ChevronLeft size={16} />
        <span className="sr-only">Previous page</span>
      </Button>
      <span className="muted">
        {page} / {totalPages}
      </span>
      <Button disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
        <ChevronRight size={16} />
        <span className="sr-only">Next page</span>
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
  placeholder = "Selectionner...",
  className = "",
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={cn("select-root", className)}>
      {label ? <label className="select-label">{label}</label> : null}
      <SelectPrimitive.Root value={value} onValueChange={onChange}>
        <SelectPrimitive.Trigger className="select-trigger">
          <SelectPrimitive.Value placeholder={placeholder} />
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
    <div className="toast-container">
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
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className={cn("dialog-content panel", wide && "dialog-wide")}>
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{title}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer">
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
