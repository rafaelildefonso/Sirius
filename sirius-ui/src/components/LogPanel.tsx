import { useEffect, useRef } from "react";
import type { LogEntry } from "../hooks/useWebSocket";

interface LogPanelProps {
  logs: LogEntry[];
}

const TAG_COLORS: Record<string, string> = {
  you: "#ffffff",
  ai: "#00aaff",
  err: "#ff3355",
  file: "#00ff88",
  sys: "#ffcc00",
};

function LogPanel({ logs }: LogPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="flex-1 overflow-y-auto p-2 min-h-0 select-text" ref={containerRef}>
      {logs.length === 0 ? (
        <p className="text-sirius-text-dim text-xs font-mono italic">
          Waiting for SIRIUS...
        </p>
      ) : (
        logs.map((entry, i) => (
          <p
            key={i}
            className="text-xs font-mono leading-relaxed whitespace-pre-wrap break-words"
            style={{ color: TAG_COLORS[entry.tag] ?? "#8090a0" }}
          >
            {entry.text}
          </p>
        ))
      )}
    </div>
  );
}

export default LogPanel;
