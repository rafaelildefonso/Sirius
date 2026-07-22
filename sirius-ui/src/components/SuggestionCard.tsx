interface SuggestionCardProps {
  text: string | null;
  onDismiss: () => void;
}

function SuggestionCard({ text, onDismiss }: SuggestionCardProps) {
  if (!text) return null;

  return (
    <div className="absolute bottom-16 left-3 z-40 animate-slide-up max-w-xs">
      <div className="bg-sirius-panel2 border border-sirius-border/60 rounded-lg px-3 py-2 shadow-lg flex items-start gap-2">
        <p className="text-sirius-text-dim text-[10px] font-mono leading-relaxed flex-1">
          {text}
        </p>
        <button
          onClick={onDismiss}
          className="shrink-0 text-sirius-text-dim hover:text-sirius-white text-[10px] leading-none mt-0.5 transition-colors"
        >
          X
        </button>
      </div>
    </div>
  );
}

export default SuggestionCard;
