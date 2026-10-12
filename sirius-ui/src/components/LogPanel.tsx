import { useEffect, useRef, useState } from "react";
import type { LogEntry } from "../hooks/useWebSocket";
import { isWindowVisible } from "../lib/windowState";

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
  const [displayed, setDisplayed] = useState<string[]>([]);
  const animatingRef = useRef(false);
  const idxRef = useRef(0);
  // Identity of the last entry rendered — detects a new log even when the
  // buffer is capped and `logs.length` stops growing.
  const lastEntryRef = useRef<LogEntry | null>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [displayed]);

  useEffect(() => {
    if (logs.length === 0) {
      lastEntryRef.current = null;
      setDisplayed([]);
      return;
    }
    const lastEntry = logs[logs.length - 1];
    if (lastEntry !== lastEntryRef.current) {
      // New entry arrived — reset to show previous entries fully + start animating new one
      lastEntryRef.current = lastEntry;
      const fullPrev = logs.slice(0, -1).map((e) => e.text);
      const newText = lastEntry.text;
      if (!isWindowVisible()) {
        // Typewriter runs a setState every 6ms — skip it while hidden.
        idxRef.current = newText.length;
        animatingRef.current = false;
        setDisplayed([...fullPrev, newText]);
        return;
      }
      setDisplayed([...fullPrev, ""]);
      idxRef.current = 0;
      animatingRef.current = true;
      const interval = setInterval(() => {
        if (!isWindowVisible()) idxRef.current = newText.length;
        idxRef.current++;
        if (idxRef.current >= newText.length) {
          clearInterval(interval);
          animatingRef.current = false;
          setDisplayed((prev) => {
            const next = [...prev];
            next[next.length - 1] = newText;
            return next;
          });
          return;
        }
        setDisplayed((prev) => {
          const next = [...prev];
          next[next.length - 1] = newText.slice(0, idxRef.current);
          return next;
        });
      }, 6);
      return () => clearInterval(interval);
    } else if (displayed.length === logs.length && !animatingRef.current) {
      // Update any changed entries (non-animated update)
      setDisplayed(logs.map((e) => e.text));
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
            {displayed[i] ?? entry.text}
            {i === logs.length - 1 && animatingRef.current && (
              <span className="typing-cursor" />
            )}
          </p>
        ))
      )}
    </div>
  );
}

export default LogPanel;
