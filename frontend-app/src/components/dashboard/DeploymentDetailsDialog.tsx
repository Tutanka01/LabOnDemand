import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Copy, ExternalLink, FolderTree, KeyRound, Terminal, X } from "lucide-react";
import { useCallback, useState } from "react";
import { getDeploymentCredentials, getDeploymentDetails } from "../../lib/api";
import { ttl } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { Deployment, DeploymentCredential, DeploymentCredentialsResponse } from "../../types/api";
import { Button, ErrorState, IconButton, LoadingState, StatusBadge, showToast } from "../ui";
import { QueryProblem, problemDetail } from "./QueryProblem";
import { VolumeBrowserDialog } from "../files/VolumeBrowserDialog";
import { TerminalDialog } from "./TerminalDialog";

const BROWSABLE_TYPES = ["vscode", "jupyter", "netbeans", "eclipse"];

export function DeploymentDetailsDialog({
  deployment,
  onClose,
  onNovnc,
}: {
  deployment: Deployment;
  onClose: () => void;
  onNovnc?: (deployment: Deployment) => void;
}) {
  const { locale, t } = useI18n();
  const [showCredentials, setShowCredentials] = useState(false);
  const [terminalPod, setTerminalPod] = useState<string | null>(null);
  const [browsePod, setBrowsePod] = useState<string | null>(null);

  const details = useQuery({
    queryKey: ["deployment-details", deployment.namespace, deployment.name],
    queryFn: () => getDeploymentDetails(deployment.namespace, deployment.name),
    staleTime: 10_000,
    // This dialog only exists while it is open: poll only while the lab is still changing state.
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data || query.state.status === "error") return false;
      const state = data.lifecycle?.state;
      if (data.lifecycle?.paused || state === "paused" || state === "deleted" || state === "expired") return false;
      const available = data.deployment.available_replicas || 0;
      const wanted = Math.max(data.deployment.replicas || deployment.replicas || 1, 1);
      return available >= wanted ? false : 5000;
    },
  });

  const credentials = useQuery({
    queryKey: ["deployment-credentials", deployment.namespace, deployment.name],
    queryFn: () => getDeploymentCredentials(deployment.namespace, deployment.name),
    enabled: showCredentials,
  });

  const deploymentType = (deployment.deployment_type || deployment.type || "").toLowerCase();
  const isVncDesktop = ["netbeans", "eclipse"].some((type) => deploymentType.includes(type));
  const canBrowseFiles = BROWSABLE_TYPES.some((type) => deploymentType.includes(type));

  return (
    <>
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel dialog-wide" aria-describedby={undefined}>
          <div className="section-head">
            <Dialog.Title asChild>
              <h2 className="min-w-0 truncate">{deployment.name}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label={t("common.close")}>
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>

          {details.isLoading ? <LoadingState /> : null}
          {details.error ? (
            <QueryProblem
              error={details.error}
              title={t("details.unavailable")}
              onRetry={() => void details.refetch()}
              retrying={details.isFetching}
              stale={Boolean(details.data)}
            />
          ) : null}

          {details.data ? (
            <div className="grid gap-4">
              <div className="lab-meta">
                <span className="badge">{details.data.deployment.namespace}</span>
                <StatusBadge state={details.data.lifecycle?.state} />
                <span className="badge">{t("details.expires", { time: ttl(deployment.expires_at, locale) })}</span>
                {!details.data.deployment.available_replicas && !details.data.lifecycle?.paused ? (
                  <span className="badge blue">{t("labs.preparing")}</span>
                ) : null}
              </div>

              <div className="grid-3">
                <div className="card grid gap-1 p-3.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">{t("details.image")}</span>
                  <strong className="block truncate-cell code-text text-sm">{details.data.deployment.image || deployment.image || "—"}</strong>
                </div>
                <div className="card grid gap-1 p-3.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">{t("details.replicas")}</span>
                  <strong className="display-figure text-2xl leading-none">
                    {details.data.deployment.available_replicas || 0}
                    <span className="text-[var(--muted)]"> / {details.data.deployment.replicas || deployment.replicas || 1}</span>
                  </strong>
                </div>
                <div className="card grid gap-1 p-3.5">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">{t("details.namespace")}</span>
                  <strong className="block truncate-cell code-text text-sm">{details.data.deployment.namespace}</strong>
                </div>
              </div>

              <div>
                <h3>{t("details.access")}</h3>
                <div className="actions-row mt-2.5">
                  {(details.data.access_urls || [])?.length ? (
                    details.data.access_urls!.map((access) => (
                      <a className="btn primary" href={access.url} target="_blank" rel="noopener noreferrer" key={access.url}>
                        <ExternalLink size={15} aria-hidden="true" />
                        {access.label || access.service
                          ? t("details.open_access", { label: access.label || access.service || "" })
                          : t("dashboard.open")}
                      </a>
                    ))
                  ) : (
                    <span className="muted">{t("labs.no_url_yet")}</span>
                  )}
                  {(isVncDesktop || details.data.novnc_endpoint) && onNovnc ? (
                    <Button onClick={() => onNovnc(deployment)}>{t("details.novnc_button")}</Button>
                  ) : null}
                </div>
              </div>

              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("details.pod")}</th>
                      <th>{t("details.status")}</th>
                      <th>{t("details.ip")}</th>
                      <th>{t("details.node")}</th>
                      <th>
                        <span className="sr-only">{t("dashboard.actions")}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(details.data.pods || []).map((pod) => (
                      <tr key={pod.name}>
                        <td className="code-text">{pod.name}</td>
                        <td>{pod.status || "—"}</td>
                        <td>{pod.pod_ip || "—"}</td>
                        <td>{pod.node_name || "—"}</td>
                        <td>
                          {pod.status === "Running" ? (
                            <div className="flex justify-end gap-1">
                              {canBrowseFiles ? (
                                <IconButton
                                  title={t("files.browse")}
                                  aria-label={t("files.browse")}
                                  onClick={() => setBrowsePod(pod.name)}
                                >
                                  <FolderTree size={14} />
                                </IconButton>
                              ) : null}
                              <IconButton
                                title={t("details.terminal")}
                                aria-label={t("details.terminal")}
                                onClick={() => setTerminalPod(pod.name)}
                              >
                                <Terminal size={14} />
                              </IconButton>
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {(details.data.services || []).length ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>{t("details.service")}</th>
                        <th>{t("details.type")}</th>
                        <th>{t("details.cluster_ip")}</th>
                        <th>{t("details.ports")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(details.data.services || []).map((service) => (
                        <tr key={service.name}>
                          <td className="code-text">{service.name}</td>
                          <td><span className="badge">{service.type}</span></td>
                          <td>{service.cluster_ip || "—"}</td>
                          <td>
                            {(service.ports || []).map((port) => (
                              <span className="badge" key={`${service.name}-${port.port}-${port.target_port}`}>
                                {port.port} → {port.target_port}{port.node_port ? ` / NodePort ${port.node_port}` : ""}
                              </span>
                            ))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              <div>
                <Button onClick={() => setShowCredentials(!showCredentials)} aria-expanded={showCredentials}>
                  <KeyRound size={16} aria-hidden="true" />
                  {showCredentials ? t("details.hide_credentials") : t("details.show_credentials")}
                </Button>
                {showCredentials && credentials.data ? (
                  <CredentialsDisplay credentials={credentials.data} />
                ) : null}
                {showCredentials && credentials.isLoading ? <LoadingState label={t("details.loading_credentials")} /> : null}
                {showCredentials && credentials.error ? (
                  <ErrorState title={t("details.credentials_unavailable")}>{problemDetail(credentials.error)}</ErrorState>
                ) : null}
              </div>
            </div>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>

    {terminalPod ? (
      <TerminalDialog
        namespace={deployment.namespace}
        pod={terminalPod}
        onClose={() => setTerminalPod(null)}
      />
    ) : null}

    {browsePod ? (
      <VolumeBrowserDialog
        target={{ namespace: deployment.namespace, pod: browsePod }}
        title={`${deployment.name} — ${t("files.title")}`}
        onClose={() => setBrowsePod(null)}
      />
    ) : null}
    </>
  );
}

function isCredential(value: unknown): value is DeploymentCredential {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function CredentialsDisplay({ credentials }: { credentials: DeploymentCredentialsResponse }) {
  const { t } = useI18n();
  const copy = useCallback((text: string) => {
    navigator.clipboard.writeText(text).then(
      () => showToast(t("common.copied"), "success"),
      () => showToast(t("details.copy_failed"), "error"),
    );
  }, [t]);

  const rows: Array<{ service: string; label: string; value?: string | number; secret?: boolean }> = [];

  const addCredential = (service: string, cred?: DeploymentCredential & { email?: string }) => {
    if (!cred) return;
    if (cred.url) rows.push({ service, label: t("details.url"), value: cred.url });
    if (cred.host) rows.push({ service, label: t("details.host"), value: cred.host });
    if (cred.port) rows.push({ service, label: t("details.port"), value: cred.port });
    if (cred.database) rows.push({ service, label: t("details.db_name"), value: cred.database });
    if (cred.username) rows.push({ service, label: t("details.username"), value: cred.username });
    if (cred.email) rows.push({ service, label: t("details.email"), value: cred.email });
    if (cred.token) rows.push({ service, label: t("details.token"), value: cred.token, secret: true });
    if (cred.password) rows.push({ service, label: t("details.password"), value: cred.password, secret: true });
    if (cred.view_only_password) rows.push({ service, label: t("details.view_only_password"), value: cred.view_only_password, secret: true });
  };

  addCredential("WordPress", credentials.wordpress as DeploymentCredential & { email?: string });
  addCredential("VS Code", credentials.vscode as DeploymentCredential);
  addCredential("Jupyter", credentials.jupyter as DeploymentCredential);
  addCredential("NetBeans", credentials.netbeans as DeploymentCredential);
  addCredential("Eclipse", credentials.eclipse as DeploymentCredential);
  addCredential(t("details.database"), credentials.database as DeploymentCredential);

  if (credentials.secrets && typeof credentials.secrets === "object") {
    Object.entries(credentials.secrets).forEach(([key, value]) => {
      rows.push({ service: credentials.type || t("details.secret"), label: key, value, secret: true });
    });
  }

  Object.entries(credentials).forEach(([service, value]) => {
    if (["type", "wordpress", "vscode", "jupyter", "netbeans", "eclipse", "database", "secrets"].includes(service)) return;
    if (isCredential(value)) addCredential(value.service || service, value);
  });

  if (rows.length === 0) {
    return <p className="muted mt-3">{t("details.no_credentials")}</p>;
  }

  return (
    <div className="table-wrap mt-3">
      <table className="data-table">
        <thead>
          <tr>
            <th>{t("details.service")}</th>
            <th>{t("details.field")}</th>
            <th>{t("details.value")}</th>
            <th>
              <span className="sr-only">{t("details.copy")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.service}-${row.label}-${index}`}>
              <td>{row.service}</td>
              <td>{row.label}</td>
              <td>{row.secret ? "******" : row.value || "—"}</td>
              <td>
                {row.value ? (
                  <IconButton
                    onClick={() => copy(String(row.value || ""))}
                    title={t("details.copy")}
                    aria-label={t("details.copy_named", { field: row.label })}
                  >
                    <Copy size={14} />
                  </IconButton>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
