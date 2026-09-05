import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import "@xterm/xterm/css/xterm.css";

interface PtyTerminalProps {
  sessionId: string;
  agent: string;
  onInput: (sessionId: string, data: string) => void;
  onResize: (sessionId: string, cols: number, rows: number) => void;
  onRegisterWrite: (sessionId: string, writeFn: (data: string) => void) => void;
  onUnregisterWrite: (sessionId: string) => void;
}

export default function PtyTerminal({
  sessionId,
  agent,
  onInput,
  onResize,
  onRegisterWrite,
  onUnregisterWrite,
}: PtyTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', monospace",
      theme: {
        background: "#0a0a0f",
        foreground: "#e0e0e0",
        cursor: "#6366f1",
        selectionBackground: "#6366f140",
      },
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();
    const unicodeAddon = new Unicode11Addon();

    term.loadAddon(fitAddon);
    term.loadAddon(webLinksAddon);
    term.loadAddon(unicodeAddon);
    term.unicode.activeVersion = "11";

    term.open(containerRef.current);
    fitAddon.fit();

    term.onData((data: string) => {
      onInput(sessionId, data);
    });

    term.onResize(({ cols, rows }) => {
      onResize(sessionId, cols, rows);
    });

    termRef.current = term;
    fitAddonRef.current = fitAddon;

    // Register write function so parent can push output
    onRegisterWrite(sessionId, (data: string) => {
      term.write(data);
    });

    const observer = new ResizeObserver(() => {
      try {
        fitAddon.fit();
      } catch {
        /* ignore */
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      onUnregisterWrite(sessionId);
      term.dispose();
      termRef.current = null;
      fitAddonRef.current = null;
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={containerRef}
      className="w-full h-full bg-[#0a0a0f]"
      style={{ minHeight: 120 }}
    />
  );
}
