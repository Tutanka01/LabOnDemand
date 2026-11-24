export type FormatLocale = "fr" | "en";

/** BCP 47 tag used with `Intl` for each UI locale. */
const INTL_TAGS: Record<FormatLocale, string> = { fr: "fr-FR", en: "en-GB" };

/**
 * UI locale for callers that do not pass one: the `lang` attribute kept in sync
 * by the i18n provider, French otherwise.
 */
export function currentLocale(): FormatLocale {
  if (typeof document === "undefined") return "fr";
  return document.documentElement.lang?.toLowerCase().startsWith("en") ? "en" : "fr";
}

function intlTag(locale?: FormatLocale): string {
  return INTL_TAGS[locale ?? currentLocale()];
}

function parseDate(value?: string | number | null): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function displayName(user?: { full_name?: string | null; username?: string | null }) {
  return user?.full_name || user?.username || roleLabel(null);
}

export function initials(user?: { full_name?: string | null; username?: string | null }) {
  const name = displayName(user).trim();
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

export function roleLabel(role?: string | null, locale: FormatLocale = currentLocale()) {
  const labels = {
    fr: {
      admin: "Administrateur",
      teacher: "Enseignant",
      student: "Étudiant",
      user: "Utilisateur",
    },
    en: {
      admin: "Administrator",
      teacher: "Teacher",
      student: "Student",
      user: "User",
    },
  };
  if (role === "admin" || role === "teacher" || role === "student") return labels[locale][role];
  return labels[locale].user;
}

export function authProviderLabel(provider?: string | null, locale: FormatLocale = currentLocale()) {
  if (provider === "oidc") return "SSO";
  if (provider === "local") return "Local";
  return provider || (locale === "en" ? "Unknown" : "Inconnu");
}

export function pct(used?: number, max?: number) {
  if (!max || max <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round(((used || 0) / max) * 100)));
}

export function pctFloat(used?: number, max?: number) {
  if (!max || max <= 0) return 0;
  return Math.max(0, Math.min(100, ((used || 0) / max) * 100));
}

export function shortDate(value?: string | null, locale?: FormatLocale) {
  const date = parseDate(value);
  if (!date) return "N/A";
  return date.toLocaleDateString(intlTag(locale), { day: "2-digit", month: "short", year: "numeric" });
}

export function fullDate(value?: string | null, locale?: FormatLocale) {
  const date = parseDate(value);
  if (!date) return "N/A";
  return date.toLocaleString(intlTag(locale), {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Formats a UNIX timestamp in seconds. */
export function dateTime(value?: number | null, locale?: FormatLocale) {
  if (!value) return "—";
  const date = parseDate(value * 1000);
  if (!date) return "—";
  return date.toLocaleString(intlTag(locale), {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte", "terabyte"] as const;

export function fileSize(bytes?: number | null, locale?: FormatLocale) {
  if (bytes === null || bytes === undefined) return "—";
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < BYTE_UNITS.length - 1) {
    value /= 1024;
    index += 1;
  }
  const digits = index === 0 ? 0 : value < 10 ? 1 : 0;
  return new Intl.NumberFormat(intlTag(locale), {
    style: "unit",
    unit: BYTE_UNITS[index],
    unitDisplay: "short",
    maximumFractionDigits: digits,
  }).format(value);
}

/** "3 days", "1 hour"… in the given locale. */
export function unitAmount(
  amount: number,
  unit: "day" | "hour" | "minute",
  locale?: FormatLocale,
  display: "long" | "short" | "narrow" = "long",
) {
  return new Intl.NumberFormat(intlTag(locale), { style: "unit", unit, unitDisplay: display }).format(amount);
}

/**
 * Compact remaining time until `value` ("2 j 3 h" / "2d 3h"), or `null` when there is
 * no expiry date or it has already passed.
 */
export function remainingTime(value?: string | null, locale?: FormatLocale): string | null {
  const date = parseDate(value);
  if (!date) return null;
  const diff = date.getTime() - Date.now();
  if (diff <= 0) return null;
  const minutes = Math.floor(diff / 60_000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days > 0) {
    return hours > 0
      ? `${unitAmount(days, "day", locale, "narrow")} ${unitAmount(hours, "hour", locale, "narrow")}`
      : unitAmount(days, "day", locale, "narrow");
  }
  if (hours > 0) return unitAmount(hours, "hour", locale, "narrow");
  return unitAmount(Math.max(minutes, 1), "minute", locale, "narrow");
}

/** True when `value` is a date in the past. */
export function isPast(value?: string | null): boolean {
  const date = parseDate(value);
  return Boolean(date && date.getTime() <= Date.now());
}

const TTL_LABELS: Record<FormatLocale, { none: string; expired: string }> = {
  fr: { none: "Aucune expiration", expired: "Expiré" },
  en: { none: "No expiry", expired: "Expired" },
};

/** Remaining lifetime of a lab, with a label when there is none or it has expired. */
export function ttl(value?: string | null, locale?: FormatLocale) {
  const labels = TTL_LABELS[locale ?? currentLocale()];
  if (!value) return labels.none;
  return remainingTime(value, locale) ?? labels.expired;
}

export function ttlPct(expiresAt?: string | null, createdDurationDays = 7) {
  if (!expiresAt) return 100;
  const created = new Date(new Date(expiresAt).getTime() - createdDurationDays * 86400000);
  const total = new Date(expiresAt).getTime() - created.getTime();
  const remaining = new Date(expiresAt).getTime() - Date.now();
  return Math.max(0, Math.min(100, Math.round((remaining / total) * 100)));
}

export function presetToResources(cpu: string, ram: string) {
  const cpuValues: Record<string, { request: string; limit: string }> = {
    "very-low": { request: "100m", limit: "200m" },
    low: { request: "250m", limit: "500m" },
    medium: { request: "500m", limit: "1000m" },
    high: { request: "1000m", limit: "2000m" },
    "very-high": { request: "2000m", limit: "4000m" },
  };
  const ramValues: Record<string, { request: string; limit: string }> = {
    "very-low": { request: "128Mi", limit: "256Mi" },
    low: { request: "256Mi", limit: "512Mi" },
    medium: { request: "512Mi", limit: "1Gi" },
    high: { request: "1Gi", limit: "2Gi" },
    "very-high": { request: "2Gi", limit: "4Gi" },
  };
  return {
    cpu: cpuValues[cpu] || cpuValues["very-low"],
    memory: ramValues[ram] || ramValues["very-low"],
  };
}

export function cpuDisplay(millicores: number | string): string {
  const m = typeof millicores === "string" ? parseFloat(millicores) : millicores;
  if (Number.isNaN(m)) return "0m";
  if (m >= 1000) return `${(m / 1000).toFixed(1)} core`;
  return `${Math.round(m)}m`;
}

export function memoryDisplay(mi: number | string): string {
  const v = typeof mi === "string" ? parseFloat(mi) : mi;
  if (Number.isNaN(v)) return "0 Mi";
  if (v >= 1024) return `${(v / 1024).toFixed(1)} Gi`;
  return `${Math.round(v)} Mi`;
}

/** Kubernetes CPU quantity ("250m", "1") to millicores. */
export function parseCpuMillicores(value?: string | null): number {
  if (!value) return 0;
  const milli = value.endsWith("m");
  const numeric = Number(milli ? value.slice(0, -1) : value);
  if (Number.isNaN(numeric)) return 0;
  return milli ? numeric : numeric * 1000;
}

/** Kubernetes memory quantity ("256Mi", "1Gi") to MiB. */
export function parseMemoryMi(value?: string | null): number {
  if (!value) return 0;
  const numeric = Number(value.replace(/[^\d.]/g, ""));
  if (Number.isNaN(numeric)) return 0;
  const lower = value.toLowerCase();
  if (lower.endsWith("gi")) return numeric * 1024;
  if (lower.endsWith("ki")) return numeric / 1024;
  return numeric;
}

/** "0.25 vCPU" for a CPU quantity, formatted for the locale. */
export function cpuLabel(value?: string | null, locale?: FormatLocale): string {
  const cores = parseCpuMillicores(value) / 1000;
  return `${new Intl.NumberFormat(intlTag(locale), { maximumFractionDigits: 2 }).format(cores)} vCPU`;
}

/** "512 MiB" / "1 GiB" for a memory quantity, formatted for the locale. */
export function memoryLabel(value?: string | null, locale?: FormatLocale): string {
  const mi = parseMemoryMi(value);
  const number = new Intl.NumberFormat(intlTag(locale), { maximumFractionDigits: 1 });
  return mi >= 1024 ? `${number.format(mi / 1024)} GiB` : `${number.format(mi)} MiB`;
}

export function defaultRuntime(deploymentType: string) {
  const defaults: Record<string, { image: string; port: number; target: number; serviceType: string }> = {
    jupyter: { image: "tutanka01/k8s:jupyter", port: 8888, target: 8888, serviceType: "NodePort" },
    vscode: { image: "codercom/code-server:4.121.0-39", port: 8080, target: 8080, serviceType: "NodePort" },
    netbeans: { image: "tutanka01/labondemand:netbeansjava", port: 6901, target: 6901, serviceType: "NodePort" },
    eclipse: { image: "tutanka01/labondemand:eclipsejava-ee-20260922", port: 6901, target: 6901, serviceType: "NodePort" },
    wordpress: { image: "bitnamilegacy/wordpress:6.8.2-debian-12-r5", port: 8080, target: 8080, serviceType: "NodePort" },
    lamp: { image: "php:8.2-apache", port: 8080, target: 80, serviceType: "NodePort" },
    mysql: { image: "phpmyadmin:latest", port: 8080, target: 80, serviceType: "NodePort" },
    custom: { image: "nginx", port: 80, target: 80, serviceType: "NodePort" },
  };
  return defaults[deploymentType] || defaults.custom;
}

const PRESET_LABELS: Record<FormatLocale, Record<string, string>> = {
  fr: { "very-low": "Très bas", low: "Bas", medium: "Moyen", high: "Élevé", "very-high": "Très élevé" },
  en: { "very-low": "Very low", low: "Low", medium: "Medium", high: "High", "very-high": "Very high" },
};

export function presetLabel(preset?: string | null, locale: FormatLocale = currentLocale()) {
  const labels = PRESET_LABELS[locale];
  return labels[preset || ""] || preset || labels.medium;
}

export function escapeHtml(str: string): string {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}
