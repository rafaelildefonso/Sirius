interface MetricBarProps {
  label: string;
  value: number;
  color?: string;
}

function MetricBar({ label, value, color = "#00aaff" }: MetricBarProps) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div className="flex items-center gap-2 text-[10px] font-mono">
      <span className="w-8 text-right text-sirius-text-dim uppercase">{label}</span>
      <div className="flex-1 h-1.5 bg-sirius-bg rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${pct}%`,
            backgroundColor: color,
          }}
        />
      </div>
      <span className="w-7 text-left text-sirius-text-dim">
        {Math.round(pct)}%
      </span>
    </div>
  );
}

export default MetricBar;
