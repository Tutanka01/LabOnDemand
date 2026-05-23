import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Copy, Terminal, X } from "lucide-react";
import { useCallback, useState } from "react";
import { getDeploymentCredentials, getDeploymentDetails } from "../../lib/api";
import { ttl } from "../../lib/format";
import type { Deployment, DeploymentCredential } from "../../types/api";
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
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>{deployment.name}</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer">
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>

          {details.isLoading ? <LoadingState /> : null}
          {details.error ? <ErrorState>Details indisponibles.</ErrorState> : null}

          {details.data ? (
            <div style={{ display: "grid", gap: 16 }}>
              <div className="lab-meta">
                <span className="badge">{details.data.deployment.namespace}</span>
                <StatusBadge state={details.data.lifecycle?.state} />
                <span className="badge">{details.data.deployment.available_replicas || 0} replicas dispo.</span>
                <span className="badge">TTL {ttl(deployment.expires_at)}</span>
                {!details.data.deployment.available_replicas ? <span className="badge blue">Preparation du lab</span> : null}
              </div>

              <div>
                <h3>Acces</h3>
                <div className="actions-row" style={{ marginTop: 10 }}>
                  {(details.data.access_urls || [])?.length ? (
                    details.data.access_urls!.map((access) => (
                      <a className="btn primary" href={access.url} target="_blank" rel="noreferrer" key={access.url}>
                        Ouvrir {access.label || access.service || "le lab"}
                      </a>
                    ))
                  ) : (
                    <span className="muted">Aucune URL disponible pour le moment.</span>
                  )}
                  {isNetBeans && onNovnc ? (
                    <Button variant="primary" onClick={() => onNovnc(deployment)}>NoVNC</Button>
                  ) : null}
                </div>
              </div>

              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Pod</th>
                      <th>Statut</th>
                      <th>IP</th>
                      <th>Noeud</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(details.data.pods || []).map((pod) => (
                      <tr key={pod.name}>
                        <td style={{ fontFamily: "monospace", fontSize: "0.82rem" }}>{pod.name}</td>
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

              <div>
                <Button onClick={() => setShowCredentials(!showCredentials)}>
                  <Terminal size={16} />
                  {showCredentials ? "Masquer identifiants" : "Afficher identifiants"}
                </Button>
                {showCredentials && credentials.data ? (
                  <CredentialsDisplay credentials={credentials.data} />
                ) : null}
                {showCredentials && credentials.isLoading ? <LoadingState label="Recuperation..." /> : null}
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

function CredentialsDisplay({ credentials }: { credentials: Record<string, DeploymentCredential> }) {
  const copy = useCallback((text: string) => {
    navigator.clipboard.writeText(text).then(
      () => showToast("Copie !", "success"),
      () => showToast("Erreur de copie", "error"),
    );
  }, []);

  const entries = Object.entries(credentials);
  if (entries.length === 0) return <span className="muted">Aucun identifiant disponible.</span>;

  return (
    <div className="table-wrap" style={{ marginTop: 12 }}>
      <table className="data-table">
        <thead>
          <tr>
            <th>Service</th>
            <th>Identifiant</th>
            <th>Mot de passe</th>
            <th>Copier</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([svc, cred]) => (
            <tr key={svc}>
              <td>{cred.service || svc}</td>
              <td>{cred.username || "N/A"}</td>
              <td>{cred.password ? "******" : "N/A"}</td>
              <td>
                {cred.password ? (
                  <IconButton onClick={() => copy(cred.password || "")} title="Copier le mot de passe">
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
