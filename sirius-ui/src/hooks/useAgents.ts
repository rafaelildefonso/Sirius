import { useCallback, useRef, useState } from "react";
import type { WsMessage } from "./useWebSocket";

export type AgentType = "claude" | "codex" | "cursor" | "opencode" | "sirius";

export interface PtySession {
  id: string;
  agent: AgentType;
  status: "starting" | "running" | "closed" | "error";
  label: string;
  color: string;
}

const AGENT_LABELS: Record<AgentType, string> = {
  claude: "Claude",
  codex: "Codex",
  cursor: "Cursor",
  opencode: "OpenCode",
  sirius: "Sirius",
};

const AGENT_COLORS: Record<AgentType, string> = {
  claude: "#d97706",
  codex: "#10b981",
  cursor: "#6366f1",
  opencode: "#ec4899",
  sirius: "#8b5cf6",
};

export { AGENT_LABELS, AGENT_COLORS };

export function useAgents() {
  const [sessions, setSessions] = useState<PtySession[]>([]);
  const [outputBuffers, setOutputBuffers] = useState<Record<string, string>>({});
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const writeRefs = useRef<Map<string, (data: string) => void>>(new Map());

  const handleAgentMessage = useCallback((data: WsMessage) => {
    switch (data.type) {
      case "agent_pty_created": {
        const session: PtySession = {
          id: String(data.session_id ?? ""),
          agent: String(data.agent ?? "claude") as AgentType,
          status: "running",
          label: AGENT_LABELS[String(data.agent ?? "claude") as AgentType] ?? String(data.agent),
          color: AGENT_COLORS[String(data.agent ?? "claude") as AgentType] ?? "#888888",
        };
        setSessions((prev) => [...prev, session]);
        setActiveSession(session.id);
        break;
      }
      case "agent_pty_output": {
        const sessionId = String(data.session_id ?? "");
        const text = String(data.data ?? "");
        // Write directly to xterm if available
        const writeFn = writeRefs.current.get(sessionId);
        if (writeFn) {
          writeFn(text);
        } else {
          // Buffer until terminal is mounted
          setOutputBuffers((prev) => ({
            ...prev,
            [sessionId]: (prev[sessionId] ?? "") + text,
          }));
        }
        break;
      }
      case "agent_pty_closed": {
        const sessionId = String(data.session_id ?? "");
        setSessions((prev) =>
          prev.map((s) => (s.id === sessionId ? { ...s, status: "closed" as const } : s))
        );
        if (activeSession === sessionId) {
          setActiveSession((prev) => {
            if (prev !== sessionId) return prev;
            const remaining = sessions.filter((s) => s.id !== sessionId && s.status !== "closed");
            return remaining.length > 0 ? remaining[0].id : null;
          });
        }
        break;
      }
    }
  }, [activeSession, sessions]);

  const createPty = useCallback(
    (send: (msg: Record<string, unknown>) => void, agent: AgentType) => {
      send({ type: "agent_create_pty", agent });
    },
    []
  );

  const sendInput = useCallback(
    (send: (msg: Record<string, unknown>) => void, sessionId: string, data: string) => {
      send({ type: "agent_pty_input", session_id: sessionId, data });
    },
    []
  );

  const resizePty = useCallback(
    (send: (msg: Record<string, unknown>) => void, sessionId: string, cols: number, rows: number) => {
      send({ type: "agent_pty_resize", session_id: sessionId, cols, rows });
    },
    []
  );

  const closePty = useCallback(
    (send: (msg: Record<string, unknown>) => void, sessionId: string) => {
      send({ type: "agent_close_pty", session_id: sessionId });
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      setOutputBuffers((prev) => {
        const next = { ...prev };
        delete next[sessionId];
        return next;
      });
      writeRefs.current.delete(sessionId);
    },
    []
  );

  const registerWrite = useCallback((sessionId: string, writeFn: (data: string) => void) => {
    writeRefs.current.set(sessionId, writeFn);
    // Flush any buffered output
    setOutputBuffers((prev) => {
      const buf = prev[sessionId];
      if (buf) {
        writeFn(buf);
        const next = { ...prev };
        delete next[sessionId];
        return next;
      }
      return prev;
    });
  }, []);

  const unregisterWrite = useCallback((sessionId: string) => {
    writeRefs.current.delete(sessionId);
  }, []);

  return {
    sessions,
    activeSession,
    setActiveSession,
    handleAgentMessage,
    createPty,
    sendInput,
    resizePty,
    closePty,
    registerWrite,
    unregisterWrite,
  };
}
