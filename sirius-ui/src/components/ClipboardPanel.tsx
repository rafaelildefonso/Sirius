import { useEffect, useRef, useState } from "react";

interface ClipboardPanelProps {
  sendCommand: (text: string) => void;
}

function ClipboardPanel({ sendCommand }: ClipboardPanelProps) {
  const [visible, setVisible] = useState(false);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState("");
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastClipRef = useRef("");

  useEffect(() => {
    const poll = async () => {
      try {
        const clip = await navigator.clipboard.readText();
        if (clip && clip.length >= 10 && clip !== lastClipRef.current) {
          lastClipRef.current = clip;
          setText(clip);
          setPreview(clip.length > 58 ? clip.slice(0, 55) + "..." : clip);
          setVisible(true);
          clearTimeout(dismissTimer.current);
          dismissTimer.current = setTimeout(() => setVisible(false), 8000);
        }
      } catch {
        // Clipboard access denied or unavailable
      }
    };
    const interval = setInterval(poll, 1500);
    return () => {
      clearInterval(interval);
      clearTimeout(dismissTimer.current);
    };
  }, []);

  const handleAction = (action: string) => {
    sendCommand(`${action}: ${text}`);
    setVisible(false);
    clearTimeout(dismissTimer.current);
  };

  const dismiss = () => {
    setVisible(false);
    clearTimeout(dismissTimer.current);
  };

  if (!visible) return null;

  return (
    <div className="fixed bottom-16 left-1/2 -translate-x-1/2 z-50 animate-slide-up">
      <div className="bg-sirius-panel2 border border-sirius-border rounded-lg shadow-lg overflow-hidden min-w-[320px] max-w-[420px]">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-sirius-border bg-sirius-panel">
          <span className="text-[10px] font-mono font-bold text-sirius-pri uppercase tracking-wider">
            CLIPBOARD
          </span>
          <button
            onClick={dismiss}
            className="text-sirius-text-dim hover:text-sirius-white text-xs transition-colors"
          >
            ✕
          </button>
        </div>
        {/* Preview */}
        <div className="px-3 py-2 border-b border-sirius-border/50">
          <p className="text-[11px] font-mono text-sirius-text-dim leading-relaxed line-clamp-2">
            {preview}
          </p>
        </div>
        {/* Action buttons */}
        <div className="flex gap-1 px-2 py-1.5">
          <button
            onClick={() => handleAction("Translate to English")}
            className="text-[10px] font-mono font-bold px-2 py-1 rounded bg-sirius-pri-dim/20 text-sirius-pri hover:bg-sirius-pri-dim/40 transition-colors flex-1"
          >
            TRADUZIR
          </button>
          <button
            onClick={() => handleAction("Summarise")}
            className="text-[10px] font-mono font-bold px-2 py-1 rounded bg-sirius-acc/20 text-sirius-acc hover:bg-sirius-acc/40 transition-colors flex-1"
          >
            RESUMIR
          </button>
          <button
            onClick={() => handleAction("Explain")}
            className="text-[10px] font-mono font-bold px-2 py-1 rounded bg-sirius-green/20 text-sirius-green hover:bg-sirius-green/40 transition-colors flex-1"
          >
            EXPLICAR
          </button>
          <button
            onClick={() => handleAction("Fix grammar and spelling")}
            className="text-[10px] font-mono font-bold px-2 py-1 rounded bg-sirius-red/20 text-sirius-red hover:bg-sirius-red/40 transition-colors flex-1"
          >
            CORRIGIR
          </button>
        </div>
      </div>
    </div>
  );
}

export default ClipboardPanel;
