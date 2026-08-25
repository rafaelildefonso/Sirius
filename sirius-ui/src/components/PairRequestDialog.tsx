interface PairRequestDialogProps {
  deviceId: string;
  name: string;
  model: string;
  platform: string;
  onResponse: (approve: boolean) => void;
}

function PairRequestDialog({
  name,
  model,
  platform,
  onResponse,
}: PairRequestDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-[360px] bg-sirius-panel border border-sirius-border rounded-lg shadow-2xl p-5">
        <h3 className="text-sirius-text font-inter font-bold text-xs uppercase tracking-wider mb-1">
          Pareamento de Celular
        </h3>
        <p className="text-sirius-text-dim text-[10px] font-mono mb-3">
          {platform}
          {model ? ` · ${model}` : ""}
        </p>
        <p className="text-sirius-text text-sm font-inter mb-5">
          <span className="font-bold">{name}</span> quer se conectar ao SIRIUS.
          Aprovar este dispositivo?
        </p>

        <div className="flex gap-2 justify-end">
          <button
            onClick={() => onResponse(false)}
            className="text-[10px] font-mono font-bold px-3 py-1.5 rounded bg-sirius-bg border border-sirius-border text-sirius-text-dim hover:text-sirius-white transition-colors"
          >
            Rejeitar
          </button>
          <button
            onClick={() => onResponse(true)}
            className="text-[10px] font-mono font-bold px-3 py-1.5 rounded bg-sirius-pri text-sirius-bg hover:brightness-110 transition-all"
          >
            Aprovar
          </button>
        </div>
      </div>
    </div>
  );
}

export default PairRequestDialog;
