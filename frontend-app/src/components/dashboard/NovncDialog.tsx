import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { getDeploymentDetails } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { Deployment } from "../../types/api";
import { IconButton, LoadingState } from "../ui";
import { problemDetail } from "./QueryProblem";

/** Remote desktop (NoVNC) of a NetBeans/Eclipse lab, embedded in a focus-trapped dialog. */
export function NovncDialog({ deployment, onClose }: { deployment: Deployment; onClose: () => void }) {
  const { t } = useI18n();
  const details = useQuery({
    queryKey: ["deployment-details", deployment.namespace, deployment.name],
    queryFn: () => getDeploymentDetails(deployment.namespace, deployment.name),
    staleTime: 30_000,
  });
  const novncUrl = details.data?.novnc_endpoint;

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay z-[60]" />
        <Dialog.Content
          className="dialog-content panel z-[61] flex h-[min(768px,calc(100vh-32px))] max-h-none w-[min(1024px,calc(100vw-16px))] flex-col overflow-hidden p-0"
          aria-describedby={undefined}
        >
          <div className="section-head mb-0 border-b border-[var(--border)] px-4 py-3">
            <Dialog.Title asChild>
              <h2 className="min-w-0 truncate">{t("details.novnc_title", { name: deployment.name })}</h2>
            </Dialog.Title>
            <div className="flex items-center gap-1">
              {novncUrl ? (
                <a
                  className="icon-btn"
                  href={novncUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t("details.novnc_new_tab")}
                  title={t("details.novnc_new_tab")}
                >
                  <ExternalLink size={16} aria-hidden="true" />
                </a>
              ) : null}
              <Dialog.Close asChild>
                <IconButton aria-label={t("common.close")}>
                  <X size={17} />
                </IconButton>
              </Dialog.Close>
            </div>
          </div>
          {details.isLoading ? (
            <div className="grid flex-1 place-items-center p-4">
              <LoadingState />
            </div>
          ) : novncUrl ? (
            <iframe className="w-full flex-1 border-0" src={novncUrl} title={t("details.novnc_frame", { name: deployment.name })} />
          ) : (
            <div className="grid flex-1 place-items-center p-4">
              <span className="muted">{details.error ? problemDetail(details.error) : t("details.novnc_unavailable")}</span>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
