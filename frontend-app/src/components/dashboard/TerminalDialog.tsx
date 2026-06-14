import * as Dialog from "@radix-ui/react-dialog";
import { Terminal as TermIcon, X } from "lucide-react";
import { useEffect, useRef } from "react";
import "@xterm/xterm/css/xterm.css";
import { IconButton } from "../ui";

export function TerminalDialog({
  namespace,
  pod,
  onClose,
}: {
  namespace: string;
  pod: string;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let mounted = true;
    let termInstance: import("@xterm/xterm").Terminal | null = null;
    let wsInstance: WebSocket | null = null;
    let observerInstance: ResizeObserver | null = null;

    (async () => {
      const { Terminal } = await import("@xterm/xterm");
      const { FitAddon } = await import("@xterm/addon-fit");

      if (!mounted || !containerRef.current) return;

      const term = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: "'Courier New', monospace",
        theme: { background: "#111617", foreground: "#f8faf9", cursor: "#0f766e" },
        scrollback: 2000,
      });
      termInstance = term;

      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.open(containerRef.current);
      fitAddon.fit();

      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(
        `${proto}//${window.location.host}/api/v1/k8s/terminal/${encodeURIComponent(namespace)}/${encodeURIComponent(pod)}`,
      );
      wsInstance = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      };
      ws.onmessage = (e) => { if (typeof e.data === "string") term.write(e.data); };
      ws.onerror = () => term.write("\r\n\x1b[31m[Erreur de connexion]\x1b[0m\r\n");
      ws.onclose = (e) => term.write(`\r\n\x1b[33m[Session terminee (code ${e.code})]\x1b[0m\r\n`);

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(data);
      });

      const observer = new ResizeObserver(() => {
        fitAddon.fit();
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
        }
      });
      observerInstance = observer;
      observer.observe(containerRef.current!);
    })();

    return () => {
      mounted = false;
      observerInstance?.disconnect();
      wsInstance?.close();
      termInstance?.dispose();
    };
  }, [namespace, pod]);

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-[52] flex h-[min(560px,calc(100vh-80px))] w-[min(960px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg bg-[#111617] shadow-[0_20px_60px_rgba(0,0,0,0.5)]"
          aria-describedby={undefined}
        >
          <div className="flex shrink-0 items-center justify-between border-b border-[#2f3d3b] bg-[#0e1413] px-3.5 py-2.5">
            <Dialog.Title asChild>
              <span className="flex items-center gap-2.5 font-mono text-[0.85rem] text-[#9fb0ad]">
                <span className="flex gap-1.5" aria-hidden="true">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f56]" />
                  <span className="h-2.5 w-2.5 rounded-full bg-[#ffbd2e]" />
                  <span className="h-2.5 w-2.5 rounded-full bg-[#27c93f]" />
                </span>
                <TermIcon size={15} className="text-[var(--primary-bright)]" />
                {namespace} / {pod}
              </span>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton
                className="border-0 bg-transparent text-[#9fb0ad]"
                aria-label="Fermer"
              >
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 p-1" ref={containerRef} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
