import { useCallback, useEffect, useMemo, useState } from "react";
import { useAgents, type AgentType, AGENT_LABELS, AGENT_COLORS } from "../hooks/useAgents";
import { useWebSocket, type WsMessage } from "../hooks/useWebSocket";
import PtyTerminal from "./PtyTerminal";
import { Terminal, Plus, X } from "./Icons";

const ALL_AGENTS: AgentType[] = ["claude", "codex", "cursor", "opencode", "sirius"];

export default function AgentsPanel() {
  const { send } = useWebSocket();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const {
    sessions,
    activeSession,
    setActiveSession,
    handleAgentMessage,
    createPty,
    closePty,
    registerWrite,
    unregisterWrite,
  } = useAgents();

  // Wire up agent messages from WS
  useEffect(() => {
    const handler = (e: Event) => {
      const raw = (e as MessageEvent).data;
      // useWebSocket dispatches JSON.stringify'd data
      let msg: Record<string, unknown>;
      if (typeof raw === "string") {
        try {
          msg = JSON.parse(raw);
        } catch {
          return;
        }
      } else if (typeof raw === "object" && raw !== null) {
        msg = raw;
      } else {
        return;
      }
      if (typeof msg.type === "string" && msg.type.startsWith("agent_pty_")) {
        handleAgentMessage(msg as WsMessage);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [handleAgentMessage]);

  const handleCreateTerminal = useCallback(
    (agent: AgentType) => {
      setDropdownOpen(false);
      createPty(send, agent);
    },
    [createPty, send]
  );

  const handleClose = useCallback(
    (sessionId: string) => {
      closePty(send, sessionId);
    },
    [closePty, send]
  );

  const handleInput = useCallback(
    (sessionId: string, data: string) => {
      const session = sessions.find((s) => s.id === sessionId);
      if (!session || session.status !== "running") return;
      send({ type: "agent_pty_input", session_id: sessionId, data });
    },
    [send, sessions]
  );

  const handleResize = useCallback(
    (sessionId: string, cols: number, rows: number) => {
      send({ type: "agent_pty_resize", session_id: sessionId, cols, rows });
    },
    [send]
  );

  const agentsWithTerminal = useMemo(() => sessions.map((s) => s.agent), [sessions]);
  const availableAgents = useMemo(
    () => ALL_AGENTS.filter((a) => !agentsWithTerminal.includes(a)),
    [agentsWithTerminal]
  );

  return (
    <div className="flex flex-col h-full w-full select-none">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-sirius-surface/50 border-b border-sirius-border">
        <div className="flex items-center gap-2">
          <Terminal size="sm" />
          <span className="text-sirius-text font-medium text-xs tracking-wide">
            AGENTES
          </span>
          <span className="text-sirius-text-dim text-[10px]">
            {sessions.length} terminal{sessions.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Agent selector bar */}
      <div className="flex items-center gap-1.5 px-3 py-1.5 bg-sirius-surface/30 border-b border-sirius-border/50">
        {sessions.map((session) => {
          const isActive = session.id === activeSession;
          return (
            <div key={session.id} className="flex items-center">
              <button
                onClick={() => setActiveSession(session.id)}
                className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-medium border transition-all ${
                  isActive
                    ? "border-sirius-pri/50 bg-sirius-pri/10 text-sirius-pri"
                    : "border-transparent text-sirius-text-dim hover:text-sirius-text hover:bg-sirius-surface/50"
                }`}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: session.color }}
                />
                {session.label}
              </button>
              <button
                onClick={() => handleClose(session.id)}
                className="ml-0.5 p-0.5 rounded text-sirius-text-dim hover:text-red-400 hover:bg-red-500/10 transition-all"
                title={`Fechar ${session.label}`}
              >
                <X size="sm" />
              </button>
            </div>
          );
        })}

        {/* Add terminal button */}
        {availableAgents.length > 0 && (
          <div className="relative">
            <button
              onClick={() => setDropdownOpen((v) => !v)}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] text-sirius-text-dim hover:text-sirius-pri hover:bg-sirius-pri/10 border border-dashed border-sirius-border hover:border-sirius-pri/50 transition-all"
            >
              <Plus size="sm" />
              Abrir
            </button>
            {dropdownOpen && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setDropdownOpen(false)}
                />
                <div className="absolute top-full left-0 mt-1 bg-sirius-surface border border-sirius-border rounded-md shadow-lg z-50 min-w-[120px]">
                  {availableAgents.map((agent) => (
                    <button
                      key={agent}
                      onClick={() => handleCreateTerminal(agent)}
                      className="flex items-center gap-2 w-full px-3 py-1.5 text-[11px] text-sirius-text hover:bg-sirius-pri/10 transition-colors"
                    >
                      <span
                        className="w-2 h-2 rounded-full"
                        style={{ backgroundColor: AGENT_COLORS[agent] }}
                      />
                      {AGENT_LABELS[agent]}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Terminal grid */}
      <div className="flex-1 overflow-hidden p-2">
        {sessions.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <span className="inline-block mb-3 text-sirius-text-dim/20">
                <Terminal size="lg" />
              </span>
              <p className="text-sirius-text-dim text-xs mb-3">
                Nenhum terminal aberto.
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {ALL_AGENTS.map((agent) => (
                  <button
                    key={agent}
                    onClick={() => handleCreateTerminal(agent)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium border border-sirius-border hover:border-sirius-pri/50 hover:bg-sirius-pri/5 text-sirius-text-dim hover:text-sirius-text transition-all"
                  >
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: AGENT_COLORS[agent] }}
                    />
                    {AGENT_LABELS[agent]}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div
            className={`grid gap-2 h-full ${
              sessions.length === 1
                ? "grid-cols-1 grid-rows-1"
                : sessions.length === 2
                ? "grid-cols-2 grid-rows-1"
                : "grid-cols-2 grid-rows-2"
            }`}
          >
            {sessions.map((session) => (
              <div
                key={session.id}
                className={`relative rounded-md overflow-hidden border transition-all ${
                  session.id === activeSession
                    ? "border-sirius-pri/50 ring-1 ring-sirius-pri/20"
                    : "border-sirius-border/50 opacity-80"
                }`}
                onClick={() => setActiveSession(session.id)}
              >
                {/* Terminal title bar */}
                <div
                  className="flex items-center gap-1.5 px-2 py-1"
                  style={{ backgroundColor: session.color + "15" }}
                >
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: session.color }}
                  />
                  <span className="text-[10px] font-medium" style={{ color: session.color }}>
                    {session.label}
                  </span>
                  <span className="text-[9px] text-sirius-text-dim ml-auto">
                    {session.status === "running"
                      ? "●"
                      : session.status === "starting"
                      ? "◌"
                      : "○"}
                  </span>
                </div>

                {/* xterm terminal */}
                <PtyTerminal
                  sessionId={session.id}
                  agent={session.agent}
                  onInput={handleInput}
                  onResize={handleResize}
                  onRegisterWrite={registerWrite}
                  onUnregisterWrite={unregisterWrite}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
