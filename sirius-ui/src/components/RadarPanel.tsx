import { useState, useRef, useEffect } from "react";

interface RadarPanelProps {
  sendMessage: (msg: Record<string, unknown>) => void;
  radarLog: string[];
  radarResults: Record<string, unknown>[];
}

const SOURCES = [
  { id: "linkedin", label: "LinkedIn" },
  { id: "google_jobs", label: "Google Jobs" },
];

export default function RadarPanel({ sendMessage, radarLog, radarResults }: RadarPanelProps) {
  const [keywords, setKeywords] = useState("");
  const [maxJobs, setMaxJobs] = useState(8);
  const [sources, setSources] = useState<string[]>(["linkedin", "google_jobs"]);
  const [scanning, setScanning] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [radarLog]);

  const toggleSource = (id: string) => {
    setSources((prev) =>
      prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]
    );
  };

  const handleScan = () => {
    if (!keywords.trim() || scanning) return;
    setScanning(true);
    sendMessage({ type: "radar_scan", keywords: keywords.trim(), maxJobs, sources });
  };

  // Reset scanning when results arrive
  useEffect(() => {
    if (radarResults.length > 0 || radarLog.some((l) => l.includes("finalizado") || l.includes("Erro"))) {
      setScanning(false);
    }
  }, [radarResults, radarLog]);

  return (
    <div className="w-full h-full flex flex-col bg-sirius-bg select-text">
      {/* Search bar */}
      <div className="flex items-center gap-2 p-3 border-b border-sirius-border">
        <input
          type="text"
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleScan()}
          placeholder="Keywords (e.g. Desenvolvedor React)"
          className="flex-1 bg-sirius-panel2 border border-sirius-border rounded px-3 py-1.5 text-xs font-mono text-sirius-text outline-none focus:border-sirius-pri transition-colors placeholder:text-sirius-text-dim"
        />
        <button
          onClick={handleScan}
          disabled={scanning || !keywords.trim()}
          className="text-[10px] font-mono font-bold px-3 py-1.5 rounded bg-sirius-pri text-sirius-bg hover:brightness-110 transition-all disabled:opacity-30"
        >
          {scanning ? "Scanning..." : "Scan"}
        </button>
      </div>

      {/* Options row */}
      <div className="flex items-center gap-4 px-3 py-1.5 border-b border-sirius-border bg-sirius-panel">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono text-sirius-text-dim">Sources:</span>
          {SOURCES.map((s) => (
            <label
              key={s.id}
              className="flex items-center gap-1 cursor-pointer"
              onClick={() => toggleSource(s.id)}
            >
              <div
                className={`w-3 h-3 rounded-full border flex items-center justify-center transition-colors ${
                  sources.includes(s.id)
                    ? "bg-sirius-pri border-sirius-pri"
                    : "bg-transparent border-sirius-text-dim"
                }`}
              >
                {sources.includes(s.id) && <span className="text-sirius-bg text-[6px] font-bold">+</span>}
              </div>
              <span className="text-[10px] font-mono text-sirius-text-dim">{s.label}</span>
            </label>
          ))}
        </div>
        <div className="flex items-center gap-1 ml-auto">
          <span className="text-[10px] font-mono text-sirius-text-dim">Max:</span>
          <input
            type="number"
            min={1}
            max={50}
            value={maxJobs}
            onChange={(e) => setMaxJobs(Math.max(1, Math.min(50, Number(e.target.value) || 8)))}
            className="w-12 bg-sirius-bg border border-sirius-border rounded px-1.5 py-0.5 text-[10px] font-mono text-sirius-text outline-none text-center"
          />
        </div>
      </div>

      {/* Results + Log split */}
      <div className="flex-1 flex flex-col min-h-0">
        {radarResults.length > 0 ? (
          <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
            {radarResults.map((job, i) => (
              <div
                key={String(job.id ?? i)}
                className="border border-sirius-border rounded p-2 hover:border-sirius-text-dim/30 transition-colors"
              >
                <p className="text-xs font-mono font-bold text-sirius-text truncate">
                  {String(job.title ?? "")}
                </p>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] font-mono text-sirius-text-dim truncate">
                    {String(job.company ?? "")}
                  </span>
                  {!!job.location && String(job.location) !== "Não informada" && (
                    <>
                      <span className="text-sirius-text-dim/30">·</span>
                      <span className="text-[10px] font-mono text-sirius-text-dim truncate">
                        {String(job.location)}
                      </span>
                    </>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`text-[9px] font-mono px-1 py-0.5 rounded ${
                    String(job.source) === "linkedin"
                      ? "bg-blue-900/30 text-blue-300"
                      : "bg-green-900/30 text-green-300"
                  }`}>
                    {String(job.source ?? "")}
                  </span>
                  {!!job.analysis && (job.analysis as Record<string, unknown>).match_score !== undefined && (
                    <span className={`text-[9px] font-mono ${
                      Number((job.analysis as Record<string, unknown>).match_score) >= 70
                        ? "text-sirius-green"
                        : Number((job.analysis as Record<string, unknown>).match_score) >= 40
                        ? "text-sirius-acc2"
                        : "text-sirius-text-dim"
                    }`}>
                      Match: {String((job.analysis as Record<string, unknown>).match_score)}%
                    </span>
                  )}
                  {!!job.url && String(job.url) && (
                    <a
                      href={String(job.url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[9px] font-mono text-sirius-pri hover:underline ml-auto"
                    >
                      Open
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sirius-text-dim text-[10px] font-mono">
              {scanning ? "Scanning..." : "No results yet. Enter keywords and press Scan."}
            </p>
          </div>
        )}

        {/* Log area */}
        {radarLog.length > 0 && (
          <div
            ref={logRef}
            className="max-h-24 overflow-y-auto border-t border-sirius-border bg-sirius-panel2 p-2"
          >
            {radarLog.map((line, i) => (
              <p key={i} className="text-[9px] font-mono text-sirius-text-dim leading-relaxed">
                {line}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
