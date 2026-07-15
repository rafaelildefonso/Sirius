interface PermissionDialogProps {
  label: string;
  toolName: string;
  onResponse: (result: "once" | "always" | "deny") => void;
}

function PermissionDialog({
  label,
  toolName,
  onResponse,
}: PermissionDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-[360px] bg-sirius-panel border border-sirius-border rounded-lg shadow-2xl p-5">
        <h3 className="text-sirius-text font-inter font-bold text-xs uppercase tracking-wider mb-1">
          Permission Required
        </h3>
        <p className="text-sirius-text-dim text-[10px] font-mono mb-3">
          {toolName}
        </p>
        <p className="text-sirius-text text-sm font-inter mb-5">{label}</p>

        <div className="flex gap-2 justify-end">
          <button
            onClick={() => onResponse("deny")}
            className="text-[10px] font-mono font-bold px-3 py-1.5 rounded bg-sirius-bg border border-sirius-border text-sirius-text-dim hover:text-sirius-white transition-colors"
          >
            Deny
          </button>
          <button
            onClick={() => onResponse("once")}
            className="text-[10px] font-mono font-bold px-3 py-1.5 rounded bg-sirius-pri-dim/30 text-sirius-pri hover:bg-sirius-pri-dim/50 transition-colors"
          >
            Allow Once
          </button>
          <button
            onClick={() => onResponse("always")}
            className="text-[10px] font-mono font-bold px-3 py-1.5 rounded bg-sirius-pri text-sirius-bg hover:brightness-110 transition-all"
          >
            Always Allow
          </button>
        </div>
      </div>
    </div>
  );
}

export default PermissionDialog;
