import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Copy, Terminal, X } from "lucide-react";
import { useCallback, useState } from "react";
import { getDeploymentCredentials, getDeploymentDetails } from "../../lib/api";
import { ttl } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { Deployment, DeploymentCredential, DeploymentCredentialsResponse } from "../../types/api";
import { Button, ErrorState, IconButton, LoadingState, StatusBadge, showToast } from "../ui";
import { TerminalDialog } from "./TerminalDialog";

export function DeploymentDetailsDialog({
  deployment,
  onClose,
  onNovnc,
}: {
  deployment: Deployment;
  onClose: () => void;
  onNovnc?: (deployment: Deployment) => void;
}) {
  const { locale } = useI18n();
  const [showCredentials, setShowCredentials] = useState(false);
  const [terminalPod, setTerminalPod] = useState<string | null>(null);

  const details = useQuery({
    queryKey: ["deployment-details", deployment.namespace, deployment.name],
    queryFn: () => getDeploymentDetails(deployment.namespace, deployment.name),
    staleTime: 10_000,
    refetchInterval: (query) => {
      const state = query.state.data?.lifecycle?.state;
      const ready = (query.state.data?.deployment.available_replicas || 0) > 0;
      return ready || state === "deleted" || state === "expired" ? false : 5000;
    },
  });

  const credentials = useQuery({
    queryKey: ["deployment-credentials", deployment.namespace, deployment.name],
    queryFn: () => getDeploymentCredentials(deployment.namespace, deployment.name),
    enabled: showCredentials,
  });

  const isNetBeans = (deployment.deployment_type || deployment.type || "").toLowerCase().includes("netbeans");

  return (
    <>
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel dialog-wide">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2 className="min-w-0 truncate">{deployment.name}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer">
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>

          {details.isLoading ? <LoadingState /> : null}
          {details.error ? <ErrorState>{locale === "fr" ? "Détails indisponibles." : "Details unavailable."}</ErrorState> : null}

          {details.data ? (
            <div className="grid gap-4">
              <div className="lab-meta">
                <span className="badge">{details.data.deployment.namespace}</span>
                <StatusBadge state={details.data.lifecycle?.state} />
                <span className="badge">{details.data.deployment.available_replicas || 0} replicas dispo.</span>
                <span className="badge">TTL {ttl(deployment.expires_at)}</span>
                {!details.data.deployment.available_replicas ? <span className="badge blue">{locale === "fr" ? "Préparation du lab" : "Preparing lab"}</span> : null}
              </div>

              <div className="grid-3">
                <div className="card grid gap-1 p-3.5">
                  <span className="text-[0.72rem] font-semibold uppercase tracking-wider text-[var(--muted)]">Image</span>
                  <strong className="block truncate-cell code-text text-[0.9rem]">{details.data.deployment.image || deployment.image || "N/A"}</strong>
                </div>
                <div className="card grid gap-1 p-3.5">
                  <span className="text-[0.72rem] font-semibold uppercase tracking-wider text-[var(--muted)]">{locale === "fr" ? "Réplicas" : "Replicas"}</span>
                  <strong className="text-[1.5rem] leading-none tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
                    {details.data.deployment.available_replicas || 0}
                    <span className="text-[var(--muted)]"> / {details.data.deployment.replicas || deployment.replicas || 1}</span>
                  </strong>
                </div>
                <div className="card grid gap-1 p-3.5">
                  <span className="text-[0.72rem] font-semibold uppercase tracking-wider text-[var(--muted)]">Namespace</span>
                  <strong className="block truncate-cell code-text text-[0.9rem]">{details.data.deployment.namespace}</strong>
                </div>
              </div>

              <div>
                <h3>{locale === "fr" ? "Accès" : "Access"}</h3>
                <div className="actions-row mt-2.5">
                  {(details.data.access_urls || [])?.length ? (
                    details.data.access_urls!.map((access) => (
                      <a className="btn primary" href={access.url} target="_blank" rel="noreferrer" key={access.url}>
                        Ouvrir {access.label || access.service || "le lab"}
                      </a>
                    ))
                  ) : (
                    <span className="muted">{locale === "fr" ? "Aucune URL disponible pour le moment." : "No URL available yet."}</span>
                  )}
                  {(isNetBeans || details.data.novnc_endpoint) && onNovnc ? (
                    <Button variant="primary" onClick={() => onNovnc(deployment)}>NoVNC</Button>
                  ) : null}
                </div>
              </div>

              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Pod</th>
                      <th>{locale === "fr" ? "Statut" : "Status"}</th>
                      <th>IP</th>
                      <th>{locale === "fr" ? "Nœud" : "Node"}</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(details.data.pods || []).map((pod) => (
                      <tr key={pod.name}>
                        <td className="code-text">{pod.name}</td>
                        <td>{pod.status || "N/A"}</td>
                        <td>{pod.pod_ip || "N/A"}</td>
                        <td>{pod.node_name || "N/A"}</td>
                        <td>
                          {pod.status === "Running" ? (
                            <IconButton
                              title="Ouvrir terminal"
                              onClick={() => setTerminalPod(pod.name)}
                            >
                              <Terminal size={14} />
                            </IconButton>
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
                        <th>Service</th>
                        <th>Type</th>
                        <th>Cluster IP</th>
                        <th>Ports</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(details.data.services || []).map((service) => (
                        <tr key={service.name}>
                          <td className="code-text">{service.name}</td>
                          <td><span className="badge">{service.type}</span></td>
                          <td>{service.cluster_ip || "N/A"}</td>
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
                <Button onClick={() => setShowCredentials(!showCredentials)}>
                  <Terminal size={16} />
                  {showCredentials
                    ? (locale === "fr" ? "Masquer identifiants" : "Hide credentials")
                    : (locale === "fr" ? "Afficher identifiants" : "Show credentials")}
                </Button>
                {showCredentials && credentials.data ? (
                  <CredentialsDisplay credentials={credentials.data} />
                ) : null}
                {showCredentials && credentials.isLoading ? <LoadingState label={locale === "fr" ? "Récupération..." : "Loading..."} /> : null}
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
    </>
  );
}

function isCredential(value: unknown): value is DeploymentCredential {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function CredentialsDisplay({ credentials }: { credentials: DeploymentCredentialsResponse }) {
  const { locale } = useI18n();
  const copy = useCallback((text: string) => {
    navigator.clipboard.writeText(text).then(
      () => showToast(locale === "fr" ? "Copié !" : "Copied!", "success"),
      () => showToast(locale === "fr" ? "Erreur de copie" : "Copy failed", "error"),
    );
  }, [locale]);

  const rows: Array<{ service: string; label: string; value?: string | number; secret?: boolean }> = [];

  const addCredential = (service: string, cred?: DeploymentCredential & { email?: string }) => {
    if (!cred) return;
    if (cred.url) rows.push({ service, label: "URL", value: cred.url });
    if (cred.host) rows.push({ service, label: "Host", value: cred.host });
    if (cred.port) rows.push({ service, label: "Port", value: cred.port });
    if (cred.database) rows.push({ service, label: "Database", value: cred.database });
    if (cred.username) rows.push({ service, label: locale === "fr" ? "Identifiant" : "Username", value: cred.username });
    if (cred.email) rows.push({ service, label: "Email", value: cred.email });
    if (cred.token) rows.push({ service, label: "Token", value: cred.token, secret: true });
    if (cred.password) rows.push({ service, label: locale === "fr" ? "Mot de passe" : "Password", value: cred.password, secret: true });
    if (cred.view_only_password) rows.push({ service, label: locale === "fr" ? "Mot de passe lecture seule" : "View-only password", value: cred.view_only_password, secret: true });
  };

  addCredential("WordPress", credentials.wordpress as DeploymentCredential & { email?: string });
  addCredential("VS Code", credentials.vscode as DeploymentCredential);
  addCredential("Jupyter", credentials.jupyter as DeploymentCredential);
  addCredential("NetBeans", credentials.netbeans as DeploymentCredential);
  addCredential(locale === "fr" ? "Base de données" : "Database", credentials.database as DeploymentCredential);

  if (credentials.secrets && typeof credentials.secrets === "object") {
    Object.entries(credentials.secrets).forEach(([key, value]) => {
      rows.push({ service: credentials.type || "Secret", label: key, value, secret: true });
    });
  }

  Object.entries(credentials).forEach(([service, value]) => {
    if (["type", "wordpress", "vscode", "jupyter", "netbeans", "database", "secrets"].includes(service)) return;
    if (isCredential(value)) addCredential(value.service || service, value);
  });

  if (rows.length === 0) {
    return <span className="muted">{locale === "fr" ? "Aucun identifiant disponible." : "No credentials available."}</span>;
  }

  return (
    <div className="table-wrap mt-3">
      <table className="data-table">
        <thead>
          <tr>
            <th>Service</th>
            <th>{locale === "fr" ? "Champ" : "Field"}</th>
            <th>{locale === "fr" ? "Valeur" : "Value"}</th>
            <th>Copier</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.service}-${row.label}-${index}`}>
              <td>{row.service}</td>
              <td>{row.label}</td>
              <td>{row.secret ? "******" : row.value || "N/A"}</td>
              <td>
                {row.value ? (
                  <IconButton onClick={() => copy(String(row.value || ""))} title={locale === "fr" ? "Copier" : "Copy"}>
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
