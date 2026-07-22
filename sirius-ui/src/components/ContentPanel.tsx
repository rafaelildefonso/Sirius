interface ContentPanelProps {
  title: string;
  text: string;
  onDismiss: () => void;
}

function ContentPanel({ title, text, onDismiss }: ContentPanelProps) {
  return (
    <div className="absolute bottom-0 left-0 right-0 z-30 animate-slide-up">
      <div className="bg-sirius-panel2 border-t border-sirius-border mx-4 mb-2 rounded-lg shadow-lg overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-3 py-1.5 border-b border-sirius-border bg-sirius-panel">
          <span className="text-[10px] font-mono font-bold text-sirius-pri uppercase tracking-wider">
            {title}
          </span>
          <button
            onClick={onDismiss}
            className="text-sirius-text-dim hover:text-sirius-white text-xs transition-colors"
          >
            ✕
          </button>
        </div>
        {/* Content */}
        <div className="px-3 py-2 max-h-[160px] overflow-y-auto">
          <pre className="text-[11px] font-mono text-sirius-text leading-relaxed whitespace-pre-wrap break-words">
            {text}
          </pre>
        </div>
      </div>
    </div>
  );
}

export default ContentPanel;
