import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { showToast } from "../components/ui";
import { ApiError, deleteDeployment, getDeploymentDetails, getDeployments, setDeploymentLifecycle } from "../lib/api";
import { useI18n } from "../lib/i18n";
import type { Deployment } from "../types/api";

/** What the user sees for a lab: the server state, overlaid with actions still in flight. */
export type LabPhase = "ready" | "starting" | "paused" | "pausing" | "resuming" | "deleting" | "creating";
export type LabAction = "pause" | "resume" | "delete";

export interface LabView {
  key: string;
  deployment: Deployment;
  phase: LabPhase;
  /** An action is in flight or waiting for the cluster to confirm it: buttons stay disabled. */
  busy: boolean;
}

type Translate = (key: string, replacements?: Record<string, string | number>) => string;

interface PendingAction {
  action: LabAction | "create";
  since: number;
  /** The API accepted the action; we are now waiting for the lab list to reflect it. */
  confirmed: boolean;
  placeholder?: Deployment;
}

export const DEPLOYMENTS_QUERY_KEY = ["deployments"] as const;

/** Poll fast while something changes, slower when a lab stays transitional for a long time. */
const FAST_POLL_MS = 3_000;
const SLOW_POLL_MS = 10_000;
const SLOW_AFTER_MS = 3 * 60_000;
/** While the list cannot be loaded (cluster unreachable, server error), try again at this pace. */
const ERROR_POLL_MS = 20_000;
/** Give up waiting for the list to reflect an accepted action after this long. */
const PENDING_TIMEOUT_MS = 2 * 60_000;

export function labKey(deployment: Pick<Deployment, "namespace" | "name">): string {
  return `${deployment.namespace}/${deployment.name}`;
}

/** Lab state as reported by the server. */
export function serverPhase(deployment: Deployment): "ready" | "starting" | "paused" {
  const lifecycle = deployment.lifecycle || deployment.lifecycle_summary;
  if (lifecycle?.paused || lifecycle?.state === "paused" || deployment.is_paused) return "paused";
  const ready = deployment.ready_replicas ?? 0;
  const wanted = Math.max(deployment.replicas ?? 1, 1);
  const state = lifecycle?.state ?? "running";
  return ready >= wanted && (state === "running" || state === "ready" || state === "unknown") ? "ready" : "starting";
}

/** Phases during which the list must keep refreshing on its own. */
export function isTransitional(phase: LabPhase): boolean {
  return phase !== "ready" && phase !== "paused";
}

/** True when at least one pod answers: the lab can be opened even if a stack is still completing. */
export function canOpen(lab: LabView): boolean {
  return (lab.phase === "ready" || lab.phase === "starting") && (lab.deployment.ready_replicas ?? 0) > 0;
}

function pendingPhase(action: PendingAction["action"]): LabPhase {
  if (action === "pause") return "pausing";
  if (action === "resume") return "resuming";
  if (action === "delete") return "deleting";
  return "creating";
}

function matchesPending(key: string, pending: PendingAction, deployment: Deployment): boolean {
  if (pending.action === "create" && pending.placeholder && !pending.placeholder.namespace) {
    return deployment.name === pending.placeholder.name;
  }
  return labKey(deployment) === key;
}

/** True once the lab list shows the result of the action. */
function isSettled(key: string, pending: PendingAction, list: Deployment[]): boolean {
  if (!pending.confirmed) return false;
  const current = list.find((item) => matchesPending(key, pending, item));
  if (pending.action === "delete") return !current;
  if (pending.action === "create") return Boolean(current);
  if (!current) return true;
  const phase = serverPhase(current);
  return pending.action === "pause" ? phase === "paused" : phase !== "paused";
}

function isRetryableError(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status >= 500;
}

/**
 * The user's lab list with live refresh: polls while a lab is changing state, refreshes on
 * window focus, and overlays pause/resume/delete/create on the cards until the cluster
 * confirms them.
 */
export function useDeployments() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Record<string, PendingAction>>({});
  const transitionalRef = useRef(false);
  const transitionalSince = useRef<number | null>(null);

  const query = useQuery({
    queryKey: DEPLOYMENTS_QUERY_KEY,
    queryFn: getDeployments,
    staleTime: 2_000,
    refetchOnWindowFocus: "always",
    refetchInterval: (current) => {
      if (current.state.status === "error") {
        return isRetryableError(current.state.error) ? ERROR_POLL_MS : false;
      }
      if (!transitionalRef.current) return false;
      const since = transitionalSince.current ?? Date.now();
      return Date.now() - since > SLOW_AFTER_MS ? SLOW_POLL_MS : FAST_POLL_MS;
    },
  });

  const serverList = useMemo(() => query.data ?? [], [query.data]);

  const labs = useMemo<LabView[]>(() => {
    const views: LabView[] = serverList.map((deployment) => {
      const key = labKey(deployment);
      const entry = Object.entries(pending).find(([pendingKey, item]) => matchesPending(pendingKey, item, deployment));
      const action = entry?.[1].action;
      const phase: LabPhase = action && action !== "create" ? pendingPhase(action) : serverPhase(deployment);
      return { key, deployment, phase, busy: Boolean(action && action !== "create") };
    });
    const placeholders = Object.entries(pending)
      .filter(([key, item]) => item.action === "create" && item.placeholder && !serverList.some((d) => matchesPending(key, item, d)))
      .map(([key, item]) => ({ key, deployment: item.placeholder!, phase: "creating" as const, busy: true }));
    return [...placeholders, ...views];
  }, [pending, serverList]);

  const transitional = labs.some((lab) => isTransitional(lab.phase)) || Object.keys(pending).length > 0;
  transitionalRef.current = transitional;
  if (transitional && transitionalSince.current === null) transitionalSince.current = Date.now();
  if (!transitional) transitionalSince.current = null;

  const syncUsage = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["quotas"] });
    void queryClient.invalidateQueries({ queryKey: ["pvcs"] });
  }, [queryClient]);

  // Drop pending overlays once the list reflects them (or after a timeout).
  useEffect(() => {
    if (!query.data) return;
    const now = Date.now();
    setPending((current) => {
      const next: Record<string, PendingAction> = {};
      let changed = false;
      for (const [key, item] of Object.entries(current)) {
        const expired = item.confirmed && now - item.since > PENDING_TIMEOUT_MS;
        if (expired || isSettled(key, item, query.data)) {
          changed = true;
        } else {
          next[key] = item;
        }
      }
      return changed ? next : current;
    });
  }, [query.data, query.dataUpdatedAt]);

  // Announce labs that just became ready, and resync quotas when everything settles.
  // Keyed by lab name: a placeholder created without a namespace still matches the real lab.
  const previousPhases = useRef<Map<string, LabPhase> | null>(null);
  const highlightTimers = useRef<number[]>([]);
  const [justReady, setJustReady] = useState<Set<string>>(() => new Set());
  useEffect(() => () => highlightTimers.current.forEach((timer) => window.clearTimeout(timer)), []);
  useEffect(() => {
    if (!query.data) return;
    const previous = previousPhases.current;
    previousPhases.current = new Map(labs.map((lab) => [lab.deployment.name, lab.phase] as const));
    if (!previous) return;
    const becameReady = labs.filter((lab) => {
      const before = previous.get(lab.deployment.name);
      // Only real start-ups: a failed pause/delete rolling back to "ready" is not news.
      return lab.phase === "ready" && (before === "starting" || before === "creating" || before === "resuming");
    });
    if (becameReady.length === 0) return;
    for (const lab of becameReady) showToast(t("labs.ready_toast", { name: lab.deployment.name }), "success");
    syncUsage();
    const keys = becameReady.map((lab) => lab.key);
    setJustReady((current) => new Set([...current, ...keys]));
    highlightTimers.current.push(
      window.setTimeout(() => {
        setJustReady((current) => {
          const copy = new Set(current);
          keys.forEach((key) => copy.delete(key));
          return copy;
        });
      }, 8_000),
    );
  }, [labs, query.data, syncUsage, t]);

  const wasTransitional = useRef(transitional);
  useEffect(() => {
    if (wasTransitional.current && !transitional) syncUsage();
    wasTransitional.current = transitional;
  }, [transitional, syncUsage]);

  const refreshList = useCallback(
    () => queryClient.invalidateQueries({ queryKey: DEPLOYMENTS_QUERY_KEY }),
    [queryClient],
  );

  const mutation = useMutation({
    mutationFn: ({ deployment, action }: { deployment: Deployment; action: LabAction }) =>
      action === "delete"
        ? deleteDeployment(deployment.namespace, deployment.name)
        : setDeploymentLifecycle(deployment.namespace, deployment.name, action),
    onMutate: ({ deployment, action }) => {
      setPending((current) => ({
        ...current,
        [labKey(deployment)]: { action, since: Date.now(), confirmed: false },
      }));
    },
    onSuccess: (_data, { deployment, action }) => {
      setPending((current) => {
        const key = labKey(deployment);
        if (!current[key]) return current;
        return { ...current, [key]: { ...current[key], since: Date.now(), confirmed: true } };
      });
      const message =
        action === "delete" ? "labs.deleted_toast" : action === "pause" ? "labs.paused_toast" : "labs.resumed_toast";
      showToast(t(message, { name: deployment.name }), "success");
    },
    onError: (error, { deployment, action }) => {
      // Roll the card back to the server state.
      setPending((current) => {
        const copy = { ...current };
        delete copy[labKey(deployment)];
        return copy;
      });
      showToast(
        t(`labs.${action}_failed`, { name: deployment.name, detail: error instanceof Error ? error.message : "" }),
        "error",
      );
    },
    onSettled: () => {
      void refreshList();
      syncUsage();
    },
  });

  const runAction = useCallback(
    (deployment: Deployment, action: LabAction) => {
      if (pending[labKey(deployment)]) return;
      mutation.mutate({ deployment, action });
    },
    [mutation, pending],
  );

  /** Shows a just-created lab right away, until the list returns it. */
  const registerCreated = useCallback(
    (lab: { name: string; namespace?: string; type: string }) => {
      const placeholder: Deployment = {
        name: lab.name,
        namespace: lab.namespace ?? "",
        type: lab.type,
        replicas: 1,
        ready_replicas: 0,
        lifecycle: { state: "starting" },
        access_url: null,
      };
      setPending((current) => ({
        ...current,
        [labKey(placeholder)]: { action: "create", since: Date.now(), confirmed: true, placeholder },
      }));
      void refreshList();
      syncUsage();
    },
    [refreshList, syncUsage],
  );

  const refreshAll = useCallback(async () => {
    await Promise.all([
      refreshList(),
      queryClient.invalidateQueries({ queryKey: ["quotas"] }),
      queryClient.invalidateQueries({ queryKey: ["pvcs"] }),
    ]);
  }, [queryClient, refreshList]);

  return {
    query,
    labs,
    justReady,
    transitional,
    runAction,
    registerCreated,
    refresh: refreshAll,
  };
}

/**
 * Opens a lab whose URL is not in the list yet. The tab is opened synchronously inside the
 * click handler (so the browser does not treat it as a pop-up), then pointed at the URL once
 * the details arrive, or closed with a message when there is none.
 */
export async function openLabViaDetails(deployment: Pick<Deployment, "namespace" | "name">, t: Translate) {
  const tab = window.open("", "_blank");
  if (tab) {
    try {
      tab.opener = null;
      tab.document.title = deployment.name;
      tab.document.body.textContent = t("labs.opening_tab");
    } catch {
      // The blank tab is same-origin; if it is not accessible we simply keep it empty.
    }
  }
  try {
    const details = await getDeploymentDetails(deployment.namespace, deployment.name);
    const url = details.access_urls?.find((access) => access.url)?.url;
    if (!url) {
      tab?.close();
      showToast(t("labs.no_url_yet"), "error");
      return;
    }
    if (tab) {
      tab.location.href = url;
    } else {
      showToast(t("labs.popup_blocked"), "error");
    }
  } catch (error) {
    tab?.close();
    showToast(t("labs.open_failed", { detail: error instanceof Error ? error.message : "" }), "error");
  }
}
