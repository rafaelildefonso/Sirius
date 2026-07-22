interface StartupPanelProps {
  action: string;
  componentKey?: string;
  statusText?: string;
  current?: number;
  total?: number;
  onComplete: () => void;
  briefing?: { greeting: string; headlines: string[] } | null;
  onDismissBriefing?: () => void;
}

const COMPONENT_LABELS: Record<string, string> = {
  llm: "LLM",
  stt: "Speech-to-Text",
  tts: "Text-to-Speech",
  init: "Initialising",
};

function StartupPanel({
  action,
  componentKey,
  statusText,
  current,
  total,
  onComplete,
  briefing,
  onDismissBriefing,
}: StartupPanelProps) {
  if (action === "hide" && !briefing) {
    return null;
  }

  const label = componentKey
    ? COMPONENT_LABELS[componentKey] ?? componentKey
    : "";

  const hasProgress = typeof current === "number" && typeof total === "number" && total > 0;
  const pct = hasProgress ? Math.round((current / total) * 100) : 0;
  const isError = action === "error";

  // If we have a briefing, show that instead of loading
  if (briefing) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 animate-fade-in">
        <div className="w-[420px] bg-sirius-panel border border-sirius-border rounded-lg p-6">
          {briefing.headlines.length > 0 ? (
            <>
              <p className="text-sirius-text font-inter font-bold text-sm mb-4 text-center">
                Principais Notícias
              </p>
              <div className="space-y-1.5 mb-4">
                {briefing.headlines.map((h, i) => (
                  <p
                    key={i}
                    className="text-sirius-text-dim text-[10px] font-mono leading-relaxed pl-2 border-l-2 border-sirius-pri/40"
                  >
                    {h}
                  </p>
                ))}
              </div>
            </>
          ) : (
            <p className="text-sirius-text font-inter font-bold text-sm mb-4 text-center">
              Nenhuma notícia disponível no momento.
            </p>
          )}

          <div className="flex justify-center">
            <button
              onClick={onDismissBriefing}
              className="text-[10px] font-mono font-bold px-4 py-1.5 rounded bg-sirius-pri/20 text-sirius-pri hover:bg-sirius-pri/40 transition-colors"
            >
              Dispensar
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 animate-fade-in">
      <div className="w-[380px] bg-sirius-panel border border-sirius-border rounded-lg p-6 text-center">
        {/* Icon */}
        {isError ? (
          <div className="w-10 h-10 mx-auto mb-3 rounded-full bg-sirius-red/20 flex items-center justify-center">
            <span className="text-sirius-red text-lg font-bold">!</span>
          </div>
        ) : (
          <div className="w-10 h-10 mx-auto mb-3 rounded-full border-2 border-sirius-pri border-t-transparent animate-spin" />
        )}

        <h2 className="text-sirius-text font-inter font-bold text-sm mb-1">
          SIRIUS
        </h2>

        {action === "ready" && (
          <p className="text-sirius-green text-[10px] font-mono">
            {label} pronto
          </p>
        )}

        {isError && (
          <>
            <p className="text-sirius-red text-[10px] font-mono mt-2">
              {statusText || label || "Erro desconhecido"}
            </p>
            <p className="text-sirius-text-dim text-[9px] font-mono mt-2">
              O aplicativo pode não funcionar corretamente.
            </p>
          </>
        )}

        {hasProgress && (
          <div className="mt-3">
            <div className="w-full h-2 bg-sirius-border rounded-full overflow-hidden">
              <div
                className="h-full bg-sirius-pri rounded-full transition-all duration-300 ease-out"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="mt-2 text-sirius-text-dim text-[10px] font-mono">
              {current}/{total} — {statusText ?? "Carregando..."}
            </p>
          </div>
        )}

        {!hasProgress && action === "status" && statusText && (
          <p className="text-sirius-text-dim text-[10px] font-mono">
            {statusText}
          </p>
        )}

        {!hasProgress && action === "show" && (
          <p className="text-sirius-text-dim text-[10px] font-mono">
            {statusText ?? "Conectando ao servidor..."}
          </p>
        )}
      </div>
    </div>
  );
}

export default StartupPanel;
