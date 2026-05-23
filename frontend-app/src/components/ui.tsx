import * as Dialog from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as Tooltip from "@radix-ui/react-tooltip";
import * as SelectPrimitive from "@radix-ui/react-select";
import { AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, Loader2, Search, X } from "lucide-react";
import { type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, useEffect, useState } from "react";

type ButtonVariant = "default" | "primary" | "danger" | "ghost";

export function Button({
  variant = "default",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button className={`btn ${variant === "default" ? "" : variant} ${className}`} {...props} />;
}

export function IconButton({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`icon-btn ${className}`} {...props} />;
}

export function SearchBox(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="search">
      <Search size={17} />
      <input {...props} />
    </label>
  );
}

export function MetricCard({ label, value, icon, hint }: { label: string; value: ReactNode; icon: ReactNode; hint?: string }) {
  return (
    <div className="card metric-card">
      <div className="metric-top">
        <span>{label}</span>
        {icon}
      </div>
      <strong className="metric-value">{value}</strong>
      {hint ? <span className="muted">{hint}</span> : null}
    </div>
  );
}

export function StatusBadge({ state }: { state?: string | null }) {
  const value = (state || "unknown").toLowerCase();
  if (value === "running" || value === "active" || value === "ready") return <span className="badge green">Actif</span>;
  if (value === "paused") return <span className="badge amber">En pause</span>;
  if (value === "starting" || value === "mixed" || value === "pending") return <span className="badge blue">Initialisation</span>;
  if (value === "error" || value === "failed") return <span className="badge red">Erreur</span>;
  if (value === "expired" || value === "deleted") return <span className="badge red">Expire</span>;
  if (value === "archived") return <span className="badge amber">Archive</span>;
  if (value === "none") return <span className="badge">Aucun</span>;
  return <span className="badge">Inconnu</span>;
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
      <Loader2 size={22} className="animate-spin" />
      <span>{label}</span>
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
          <div className="actions-row" style={{ justifyContent: "end", marginTop: 18 }}>
            <Dialog.Close asChild>
              <Button>Annuler</Button>
            </Dialog.Close>
            <Dialog.Close asChild>
              <Button variant={destructive ? "danger" : "primary"} onClick={() => void onConfirm()}>
                {confirmLabel}
              </Button>
            </Dialog.Close>
          </div>
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
  return <TabsPrimitive.List className={`tab-list ${className}`}>{children}</TabsPrimitive.List>;
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
      <button className="btn" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <ChevronLeft size={16} />
      </button>
      <span className="muted">
        {page} / {totalPages}
      </span>
      <button className="btn" disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
        <ChevronRight size={16} />
      </button>
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
    <div className={`select-root ${className}`}>
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
        <div key={t.id} className={`toast ${t.type}`}>
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
    <div className={`field ${full ? "full" : ""}`}>
      <label>
        {label}
        {required ? <span className="required"> *</span> : null}
      </label>
      {children}
      {error ? <span className="badge red">{error}</span> : null}
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
        <Dialog.Content className={`dialog-content panel ${wide ? "dialog-wide" : ""}`}>
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
