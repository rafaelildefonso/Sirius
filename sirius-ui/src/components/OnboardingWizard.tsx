import { useState, useEffect, useCallback, useRef } from "react";
import type { PermissionItem } from "../hooks/useWebSocket";

interface OnboardingWizardProps {
  initialStep?: string;
  initialConfig?: Record<string, string>;
  permissions: PermissionItem[];
  onSave: (cfg: Record<string, unknown>, secrets: Record<string, string>, perms: Record<string, boolean>) => void;
  onDone: () => void;
}

const SECRET_KEYS = [
  { key: "gemini_api_key", label: "Gemini API Key", requiredFor: "gemini" },
  { key: "openrouter_api_key", label: "OpenRouter API Key", requiredFor: null },
  { key: "tavily_api_key", label: "Tavily API Key", requiredFor: null },
  { key: "serpapi_key", label: "SerpAPI Key", requiredFor: null },
];

const PERMISSION_META: Record<string, { label: string; description: string }> = {
  control_mouse_keyboard:    { label: "Controlar Mouse e Teclado",  description: "Mover o cursor, clicar e digitar automaticamente." },
  view_screen:               { label: "Visualizar Tela",            description: "Capturar e analisar a tela do computador." },
  view_camera:               { label: "Acessar Câmera",             description: "Capturar imagens da webcam." },
  manage_files:              { label: "Gerenciar Arquivos",          description: "Criar, editar, mover e excluir arquivos e pastas." },
  execute_commands:          { label: "Executar Comandos e Código",  description: "Rodar scripts, compilar e executar programas." },
  access_web_browser:        { label: "Controlar Navegador",         description: "Abrir sites, pesquisar e interagir com páginas web." },
  open_applications:         { label: "Abrir Aplicativos",           description: "Iniciar programas instalados no computador." },
  access_personal_accounts:  { label: "Acessar Contas Pessoais",    description: "Ler e gerenciar Gmail, Google Calendar e Notion." },
  send_messages:             { label: "Enviar Mensagens",            description: "Enviar mensagens via WhatsApp, Telegram e lembretes." },
};

const TOTAL_STEPS = 5;

export default function OnboardingWizard({ initialStep, initialConfig, permissions, onSave, onDone }: OnboardingWizardProps) {
  const [step, setStep] = useState(1);
  const [mode, setMode] = useState<string>(initialConfig?.assistant_mode ?? "gemini");
  const [name, setName] = useState(initialConfig?.user_name ?? "");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [perms, setPerms] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);

  useEffect(() => {
    const p: Record<string, boolean> = {};
    for (const item of permissions) {
      p[item.key] = item.granted !== false;
    }
    for (const key of Object.keys(PERMISSION_META)) {
      if (p[key] === undefined) {
        p[key] = true;
      }
    }
    setPerms(p);
  }, [permissions]);

  const updateSecret = (key: string, value: string) => {
    setSecrets((prev) => ({ ...prev, [key]: value }));
  };

  const togglePerm = (key: string) => {
    setPerms((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Fallback timeout: if onboarding_saved ack never arrives, force-close after 10s
  useEffect(() => {
    if (!saving) return;
    savingRef.current = true;
    const timer = setTimeout(() => {
      if (savingRef.current) {
        savingRef.current = false;
        setSaving(false);
        onDone();
      }
    }, 10000);
    return () => {
      clearTimeout(timer);
      savingRef.current = false;
    };
  }, [saving, onDone]);

  const handleFinish = useCallback(() => {
    const cfg: Record<string, unknown> = {
      assistant_mode: mode,
      user_name: name,
    };
    setSaving(true);
    onSave(cfg, secrets, perms);
    // NOTE: onDone is NOT called here — it's triggered automatically
    // by the WebSocket hook when onboarding_saved ack is received.
    // If the ack never comes, the timeout above force-closes after 10s.
  }, [mode, name, secrets, perms, onSave]);

  const nextStep = () => setStep((s) => Math.min(s + 1, TOTAL_STEPS));
  const prevStep = () => setStep((s) => Math.max(s - 1, 1));

  const canProceed = () => {
    if (step === 1) return !!mode;
    if (step === 2) return name.trim().length >= 2;
    if (step === 3) {
      if (mode === "gemini" && !secrets["gemini_api_key"]) return false;
      return true;
    }
    return true;
  };

  const stepTitles = ["Welcome & Mode", "Your Name", "API Keys", "Permissions", "Summary"];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-fade-in">
      <div className="w-[520px] max-h-[90vh] bg-sirius-panel border border-sirius-border rounded-lg shadow-2xl flex flex-col overflow-hidden">
        <div className="flex items-center gap-2 px-5 py-4 border-b border-sirius-border">
          
          <h2 className="text-sirius-text font-inter font-bold text-sm">SIRIUS — First Time Setup</h2>
        </div>

        <div className="px-5 pt-3 pb-1">
          <div className="flex gap-1">
            {Array.from({ length: TOTAL_STEPS }, (_, i) => (
              <div
                key={i}
                className={`flex-1 h-1 rounded-full transition-colors ${
                  i + 1 <= step ? "bg-sirius-pri" : "bg-sirius-border"
                }`}
              />
            ))}
          </div>
          <p className="text-sirius-text-dim text-[10px] font-mono mt-2">
            Step {step} of {TOTAL_STEPS} — {stepTitles[step - 1]}
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sirius-text text-xs font-mono">How would you like SIRIUS to run?</p>
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => setMode("gemini")}
                  className={`p-4 rounded-lg border text-left transition-all ${
                    mode === "gemini"
                      ? "border-sirius-pri bg-sirius-pri-dim/20"
                      : "border-sirius-border hover:border-sirius-text-dim"
                  }`}
                >
                  
                  <p className="text-sirius-text text-xs font-bold font-mono">Gemini Live</p>
                  <p className="text-sirius-text-dim text-[10px] font-mono mt-1">
                    Cloud-based. Requires a Gemini API key. Low latency voice conversation.
                  </p>
                </button>
                <button
                  onClick={() => setMode("local")}
                  className={`p-4 rounded-lg border text-left transition-all ${
                    mode === "local"
                      ? "border-sirius-pri bg-sirius-pri-dim/20"
                      : "border-sirius-border hover:border-sirius-text-dim"
                  }`}
                >
                  
                  <p className="text-sirius-text text-xs font-bold font-mono">Local Mode</p>
                  <p className="text-sirius-text-dim text-[10px] font-mono mt-1">
                    Runs entirely offline. Uses Ollama/OpenAI-compatible LLMs on your machine.
                  </p>
                </button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sirius-text text-xs font-mono">What should I call you?</p>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name..."
                className="w-full bg-sirius-bg border border-sirius-border rounded px-3 py-2 text-sm font-mono text-sirius-text outline-none focus:border-sirius-pri transition-colors placeholder:text-sirius-text-dim"
                autoFocus
              />
              {name.trim().length > 0 && name.trim().length < 2 && (
                <p className="text-sirius-red text-[10px] font-mono">Name must be at least 2 characters.</p>
              )}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <p className="text-sirius-text text-xs font-mono">Configure your API keys.</p>
              {SECRET_KEYS.map(({ key, label, requiredFor }) => {
                const required = requiredFor === mode;
                return (
                  <div key={key}>
                    <label className="text-sirius-text-dim text-[10px] font-mono block mb-1">
                      {label}{required ? " *" : ""} {!required && <span className="text-sirius-text-dim/50">(optional)</span>}
                    </label>
                    <input
                      type="password"
                      value={secrets[key] ?? ""}
                      onChange={(e) => updateSecret(key, e.target.value)}
                      placeholder={required ? "Required" : "Optional"}
                      className={`w-full bg-sirius-bg border rounded px-3 py-2 text-xs font-mono text-sirius-text outline-none transition-colors placeholder:text-sirius-text-dim ${
                        required && !secrets[key]
                          ? "border-sirius-red/50 focus:border-sirius-red"
                          : "border-sirius-border focus:border-sirius-pri"
                      }`}
                    />
                    {required && !secrets[key] && (
                      <p className="text-sirius-red text-[10px] font-mono mt-1">Required for {mode} mode.</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {step === 4 && (
            <div className="space-y-3">
              <p className="text-sirius-text text-xs font-mono">Review permissions SIRIUS needs on your PC.</p>
              <p className="text-sirius-text-dim text-[10px] font-mono">
                All enabled by default. Turn off anything you're not comfortable with.
              </p>
              {Object.entries(PERMISSION_META).map(([key, meta]) => {
                const enabled = perms[key] !== false;
                return (
                  <div
                    key={key}
                    className="flex items-start gap-3 p-2.5 rounded-lg border transition-colors cursor-pointer"
                    style={{
                      borderColor: enabled ? "var(--sirius-border)" : "var(--sirius-red-dim)",
                      opacity: enabled ? 1 : 0.6,
                    }}
                    onClick={() => togglePerm(key)}
                  >
                    <div
                      className={`mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors ${
                        enabled
                          ? "bg-sirius-pri border-sirius-pri"
                          : "bg-transparent border-sirius-text-dim"
                      }`}
                    >
                      {enabled && <span className="text-sirius-bg text-[8px] font-bold">+</span>}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={`text-xs font-mono font-bold ${enabled ? "text-sirius-text" : "text-sirius-text-dim"}`}>
                        {meta.label}
                      </p>
                      <p className="text-sirius-text-dim text-[10px] font-mono mt-0.5">{meta.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {step === 5 && (
            <div className="space-y-4">
              <p className="text-sirius-text text-xs font-mono">Review your choices before we start.</p>
              <SummaryRow label="Mode" value={mode === "gemini" ? "Gemini Live (Cloud)" : "Local (Ollama/OpenAI)"} />
              <SummaryRow label="Name" value={name} />
              <SummaryRow
                label="API Keys"
                value={
                  Object.entries(secrets)
                    .filter(([, v]) => v)
                    .map(([k]) => k.replace("_api_key", "").replace("_", " ").replace(/\b\w/g, (c) => c.toUpperCase()))
                    .join(", ") || "None configured"
                }
              />
              <SummaryRow
                label="Permissions"
                value={`${Object.values(perms).filter(Boolean).length} / ${Object.keys(perms).length} enabled`}
              />
              <button
                onClick={handleFinish}
                disabled={saving}
                className="w-full mt-4 py-3 rounded-lg bg-sirius-pri text-sirius-bg text-xs font-mono font-bold hover:brightness-110 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {saving ? "Saving..." : "Start SIRIUS"}
              </button>
            </div>
          )}
        </div>

        <div className="flex justify-between px-5 py-3 border-t border-sirius-border">
          <button
            onClick={prevStep}
            disabled={step === 1}
            className="text-[10px] font-mono font-bold px-3 py-1.5 rounded text-sirius-text-dim hover:text-sirius-white transition-colors disabled:opacity-30"
          >
            ← Back
          </button>
          {step < TOTAL_STEPS && (
            <button
              onClick={nextStep}
              disabled={!canProceed()}
              className="text-[10px] font-mono font-bold px-4 py-1.5 rounded bg-sirius-pri text-sirius-bg hover:brightness-110 transition-all disabled:opacity-30"
            >
              Continue →
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <p className="text-sirius-text-dim text-[10px] font-mono w-24 shrink-0">{label}</p>
      <p className="text-sirius-text text-[10px] font-mono break-all">{value}</p>
    </div>
  );
}
