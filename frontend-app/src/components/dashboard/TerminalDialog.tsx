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
          style={{
            position: "fixed",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            width: "min(960px, calc(100vw - 32px))",
            height: "min(560px, calc(100vh - 80px))",
            display: "flex",
            flexDirection: "column",
            background: "#111617",
            borderRadius: 8,
            overflow: "hidden",
            zIndex: 52,
            boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
          }}
          aria-describedby={undefined}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "10px 14px",
              borderBottom: "1px solid #2f3d3b",
              flexShrink: 0,
            }}
          >
            <Dialog.Title asChild>
              <span
                style={{
                  color: "#9fb0ad",
                  fontFamily: "monospace",
                  fontSize: "0.85rem",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <TermIcon size={15} />
                {namespace} / {pod}
              </span>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton
                aria-label="Fermer"
                style={{ color: "#9fb0ad", border: "none", background: "transparent" }}
              >
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>
          <div ref={containerRef} style={{ flex: 1, minHeight: 0, padding: "4px" }} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
