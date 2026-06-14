export function displayName(user?: { full_name?: string | null; username?: string | null }) {
  return user?.full_name || user?.username || "Utilisateur";
}

export function initials(user?: { full_name?: string | null; username?: string | null }) {
  const name = displayName(user).trim();
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

export function roleLabel(role?: string | null, locale: "fr" | "en" = "fr") {
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

export function authProviderLabel(provider?: string | null) {
  if (provider === "oidc") return "SSO";
  if (provider === "local") return "Local";
  return provider || "Inconnu";
}

export function pct(used?: number, max?: number) {
  if (!max || max <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round(((used || 0) / max) * 100)));
}

export function pctFloat(used?: number, max?: number) {
  if (!max || max <= 0) return 0;
  return Math.max(0, Math.min(100, ((used || 0) / max) * 100));
}

export function shortDate(value?: string | null) {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "N/A";
  return date.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

export function fullDate(value?: string | null) {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "N/A";
  return date.toLocaleString("fr-FR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ttl(value?: string | null) {
  if (!value) return "Aucune expiration";
  const diff = new Date(value).getTime() - Date.now();
  if (diff <= 0) return "Expiré";
  const minutes = Math.floor(diff / 60_000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  if (days > 0) return `${days}j ${hours}h`;
  if (hours > 0) return `${hours}h`;
  return `${minutes}min`;
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

export function defaultRuntime(deploymentType: string) {
  const defaults: Record<string, { image: string; port: number; target: number; serviceType: string }> = {
    jupyter: { image: "tutanka01/k8s:jupyter", port: 8888, target: 8888, serviceType: "NodePort" },
    vscode: { image: "codercom/code-server:4.121.0-39", port: 8080, target: 8080, serviceType: "NodePort" },
    netbeans: { image: "tutanka01/labondemand:netbeansjava", port: 6901, target: 6901, serviceType: "NodePort" },
    wordpress: { image: "bitnamilegacy/wordpress:6.8.2-debian-12-r5", port: 8080, target: 8080, serviceType: "NodePort" },
    lamp: { image: "php:8.2-apache", port: 8080, target: 80, serviceType: "NodePort" },
    mysql: { image: "phpmyadmin:latest", port: 8080, target: 80, serviceType: "NodePort" },
    custom: { image: "nginx", port: 80, target: 80, serviceType: "NodePort" },
  };
  return defaults[deploymentType] || defaults.custom;
}

export function presetLabel(preset?: string | null) {
  const labels: Record<string, string> = {
    "very-low": "Très bas",
    low: "Bas",
    medium: "Moyen",
    high: "Élevé",
    "very-high": "Très élevé",
  };
  return labels[preset || ""] || preset || "Moyen";
}

export function colorForId(id: number): string {
  const colors = ["#0f766e", "#2463eb", "#7c3aed", "#b45309", "#be123c", "#15803d", "#1d4ed8", "#a21caf"];
  return colors[Math.abs(id) % colors.length];
}

export function escapeHtml(str: string): string {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(str));
  return div.innerHTML;
}
