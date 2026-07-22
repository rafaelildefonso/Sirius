import { useState, useEffect } from "react";
import type { PermissionItem } from "../hooks/useWebSocket";

interface SettingsModalProps {
  onClose: () => void;
  onSaveConfig?: (
    payload: Record<string, unknown>,
    secrets: Record<string, string>,
    permissions?: Record<string, boolean>,
  ) => void;
  config?: Record<string, string> | null;
  permissions?: PermissionItem[];
  autoStart?: boolean;
  onSetAutoStart?: (enabled: boolean) => void;
  googleConnected?: boolean;
  googleAuthMsg?: string | null;
  googleAuthLoading?: boolean;
  onCheckGoogleStatus?: () => void;
  onRunGoogleAuth?: () => void;
  send?: (msg: Record<string, unknown>) => void;
}

type SettingsTab = "general" | "preferences" | "permissions" | "engines";

const SECRET_KEYS = [
  "gemini_api_key",
  "openrouter_api_key",
  "tavily_api_key",
  "serpapi_key",
  "elevenlabs_api_key",
  "google_client_id",
  "google_client_secret",
  "notion_token",
  "notion_database_id",
];

function SettingsModal({
  onClose,
  onSaveConfig,
  config,
  permissions,
  autoStart,
  onSetAutoStart,
  googleConnected,
  googleAuthMsg,
  googleAuthLoading,
  onCheckGoogleStatus,
  onRunGoogleAuth,
  send,
}: SettingsModalProps) {
  const [tab, setTab] = useState<SettingsTab>("general");
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [localPerms, setLocalPerms] = useState<Record<string, boolean>>({});

  // Switch away from engines tab when mode is not local
  useEffect(() => {
    if (tab === "engines" && cfg["assistant_mode"] !== "local") {
      setTab("general");
    }
  }, [cfg["assistant_mode"], tab]);

  // Sync local cfg/secrets whenever config prop changes
  useEffect(() => {
    if (!config) return;
    const s: Record<string, string> = {};
    for (const key of SECRET_KEYS) {
      if (config[key]) {
        s[key] = config[key];
      }
    }
    setCfg({ ...config });
    setSecrets(s);
    setLoaded(true);
  }, [config]);

  // Initialize permissions map once
  useEffect(() => {
    if (!permissions) return;
    const p: Record<string, boolean> = {};
    for (const item of permissions) {
      p[item.key] = item.granted !== false;
    }
    setLocalPerms(p);
  }, [permissions]);

  useEffect(() => {
    onCheckGoogleStatus?.();
  }, [onCheckGoogleStatus]);

  const handleSave = () => {
    if (onSaveConfig) {
      onSaveConfig(cfg, secrets, localPerms);
    }
    onClose();
  };

  const updateCfg = (key: string, value: string) => {
    setCfg((prev) => ({ ...prev, [key]: value }));
  };

  const updateSecret = (key: string, value: string) => {
    setSecrets((prev) => ({ ...prev, [key]: value }));
  };

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "general", label: "General" },
    { id: "preferences", label: "Preferências" },
    { id: "permissions", label: "Permissions" },
    ...(cfg["assistant_mode"] === "local" ? [{ id: "engines" as SettingsTab, label: "Local Engines" }] : []),
  ];

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-[480px] max-h-[80vh] bg-sirius-panel border border-sirius-border rounded-lg shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-sirius-border">
          <div className="flex items-center gap-2">
            <h2 className="text-sirius-text font-inter font-bold text-sm">
              Settings
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-sirius-text-dim hover:text-sirius-white text-xs transition-colors"
          >
            X
          </button>
        </div>

        {/* Sidebar + Content */}
        <div className="flex flex-1 min-h-0">
          <nav className="w-28 border-r border-sirius-border p-2 space-y-1">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`w-full text-left text-[10px] font-mono font-bold px-2 py-1.5 rounded transition-colors ${
                  tab === t.id
                    ? "text-sirius-pri bg-sirius-pri-dim/20"
                    : "text-sirius-text-dim hover:text-sirius-white"
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <div className="flex-1 overflow-y-auto p-4">
            {!loaded ? (
              <p className="text-sirius-text-dim text-xs">Loading...</p>
            ) : tab === "preferences" ? (
                <div className="space-y-3">
                  <SectionTitle>Funcionalidades de voz</SectionTitle>
                  <ToggleRow
                    label="Falar Saudações"
                    value={cfg["speak_greeting_enabled"] !== "false"}
                    onChange={(v) => updateCfg("speak_greeting_enabled", v ? "true" : "false")}
                  />
                  <ToggleRow
                    label="Falar Notícias"
                    value={cfg["speak_news_enabled"] !== "false"}
                    onChange={(v) => updateCfg("speak_news_enabled", v ? "true" : "false")}
                  />
                  <ToggleRow
                    label="Falar Briefing"
                    value={cfg["speak_briefing_enabled"] !== "false"}
                    onChange={(v) => updateCfg("speak_briefing_enabled", v ? "true" : "false")}
                  />
                  <ToggleRow
                    label="Falar Sugestões Proativas"
                    value={cfg["speak_proactive_enabled"] !== "false"}
                    onChange={(v) => updateCfg("speak_proactive_enabled", v ? "true" : "false")}
                  />
                </div>
) : tab === "general" ? (
              <div className="space-y-3">
                <SectionTitle>API Keys</SectionTitle>
                <div className="flex items-center gap-1">
                  <ApiKeyInput
                    label="Gemini"
                    value={secrets["gemini_api_key"] ?? ""}
                    onChange={(v) => updateSecret("gemini_api_key", v)}
                  />
                  {secrets["gemini_api_key"] ? (
                    <span className="text-[9px] text-green-400 font-mono shrink-0 self-end mb-1">key loaded</span>
                  ) : (
                    <span className="text-[9px] text-red-400 font-mono shrink-0 self-end mb-1">not set</span>
                  )}
                </div>
                <ApiKeyInput
                  label="OpenRouter"
                  value={secrets["openrouter_api_key"] ?? ""}
                  onChange={(v) => updateSecret("openrouter_api_key", v)}
                />
                <ApiKeyInput
                  label="Tavily"
                  value={secrets["tavily_api_key"] ?? ""}
                  onChange={(v) => updateSecret("tavily_api_key", v)}
                />
                <ApiKeyInput
                  label="SerpAPI"
                  value={secrets["serpapi_key"] ?? ""}
                  onChange={(v) => updateSecret("serpapi_key", v)}
                />
                <ApiKeyInput
                  label="ElevenLabs"
                  value={secrets["elevenlabs_api_key"] ?? ""}
                  onChange={(v) => updateSecret("elevenlabs_api_key", v)}
                />
                <Separator />
                <SectionTitle>Integrações</SectionTitle>
                <TextInput
                  label="Google Client ID"
                  value={secrets["google_client_id"] ?? ""}
                  onChange={(v) => updateSecret("google_client_id", v)}
                />
                <ApiKeyInput
                  label="Google Client Secret"
                  value={secrets["google_client_secret"] ?? ""}
                  onChange={(v) => updateSecret("google_client_secret", v)}
                />
                {/* Google Connect button + status */}
                <div className="flex items-center gap-2 py-1">
                  <button
                    onClick={onRunGoogleAuth}
                    disabled={googleAuthLoading}
                    className={`text-[10px] font-mono font-bold px-3 py-1.5 rounded transition-colors ${
                      googleAuthLoading
                        ? "text-sirius-text-dim bg-sirius-border/30 cursor-not-allowed"
                        : googleConnected
                          ? "text-green-400 bg-green-400/10 hover:bg-green-400/20"
                          : "text-sirius-pri bg-sirius-pri-dim/20 hover:bg-sirius-pri-dim/40"
                    }`}
                  >
                    {googleAuthLoading
                      ? "AUTHORIZING..."
                      : googleConnected
                        ? "✓ GOOGLE CONNECTED"
                        : "CONNECT GOOGLE"}
                  </button>
                  <span className="text-[9px] font-mono text-sirius-text-dim flex-1">
                    {googleAuthMsg ?? (googleConnected ? "Token válido" : "Não conectado")}
                  </span>
                </div>
                <ApiKeyInput
                  label="Notion Token"
                  value={secrets["notion_token"] ?? ""}
                  onChange={(v) => updateSecret("notion_token", v)}
                />
                <TextInput
                  label="Notion Database ID"
                  value={secrets["notion_database_id"] ?? ""}
                  onChange={(v) => updateSecret("notion_database_id", v)}
                />
                <Separator />
                <SectionTitle>System</SectionTitle>
                <TextInput
                  label="User Name"
                  value={cfg["user_name"] ?? ""}
                  onChange={(v) => updateCfg("user_name", v)}
                />
                <SelectInput
                  label="OS"
                  value={cfg["os_system"] ?? "windows"}
                  options={[
                    { value: "windows", label: "Windows" },
                    { value: "darwin", label: "macOS" },
                    { value: "linux", label: "Linux" },
                  ]}
                  onChange={(v) => updateCfg("os_system", v)}
                />
                <SelectInput
                  label="Mode"
                  value={cfg["assistant_mode"] ?? "gemini"}
                  options={[
                    { value: "gemini", label: "Gemini Live (Cloud)" },
                    { value: "local", label: "Local (Ollama/OpenAI)" },
                  ]}
                  onChange={(v) => {
                    updateCfg("assistant_mode", v);
                    updateCfg("llm_provider", v === "gemini" ? "gemini" : "ollama");
                  }}
                />
                <div className="flex items-center justify-between py-1">
                  <label className="text-sirius-text-dim text-[10px] font-mono">
                    Iniciar com o Windows
                  </label>
                  <button
                    onClick={() => onSetAutoStart?.(!autoStart)}
                    className={`w-8 h-4 rounded-full transition-colors relative ${
                      autoStart ? "bg-sirius-pri" : "bg-sirius-border"
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all ${
                        autoStart ? "left-4" : "left-0.5"
                      }`}
                    />
                  </button>
                </div>
                <div className="flex items-center justify-between py-1">
                  <label className="text-sirius-text-dim text-[10px] font-mono">
                    Cor da Interface
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={cfg["ui_color"] ?? "#00d4ff"}
                      onChange={(e) => updateCfg("ui_color", e.target.value)}
                      className="w-6 h-6 rounded cursor-pointer border border-sirius-border bg-transparent"
                    />
                    <span className="text-[9px] font-mono text-sirius-text-dim w-14">
                      {cfg["ui_color"] ?? "#00d4ff"}
                    </span>
                  </div>
                </div>
                <div className="flex justify-end py-1">
                  <button
                    onClick={() => send?.({ type: "create_desktop_shortcut" })}
                    className="text-[10px] font-mono font-bold px-2 py-1 rounded text-sirius-text-dim hover:text-sirius-white border border-sirius-border hover:border-sirius-pri transition-colors"
                  >
                    + Criar Atalho Desktop
                  </button>
                </div>
                <Separator />
                <SectionTitle>Funcionalidades</SectionTitle>
                <ToggleRow
                  label="Briefing Matinal"
                  value={cfg["morning_brief_enabled"] !== "false"}
                  onChange={(v) => updateCfg("morning_brief_enabled", v ? "true" : "false")}
                />
                <ToggleRow
                  label="Sugestões Proativas"
                  value={cfg["proactive_mode_enabled"] !== "false"}
                  onChange={(v) => updateCfg("proactive_mode_enabled", v ? "true" : "false")}
                />
              </div>
) : tab === "permissions" ? (
              <div className="space-y-3">
                <SectionTitle>Tool Permissions</SectionTitle>
                {permissions && permissions.length > 0 ? (
                  <div className="space-y-2">
                    {permissions.map((item) => {
                      const enabled = localPerms[item.key] !== false;
                      return (
                        <div
                          key={item.key}
                          className="flex items-start gap-3 p-2 rounded-lg border transition-colors cursor-pointer"
                          style={{
                            borderColor: enabled ? "var(--sirius-border)" : "var(--sirius-red-dim)",
                            opacity: enabled ? 1 : 0.6,
                          }}
                          onClick={() => setLocalPerms((prev) => ({ ...prev, [item.key]: !prev[item.key] }))}
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
                            <p className={`text-[10px] font-mono font-bold ${enabled ? "text-sirius-text" : "text-sirius-text-dim"}`}>
                              {item.label}
                            </p>
                            <p className="text-sirius-text-dim text-[9px] font-mono mt-0.5">{item.description}</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sirius-text-dim text-[10px] font-mono">
                    Loading permissions...
                  </p>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <SectionTitle>Speech-to-Text</SectionTitle>
                <SelectInput
                  label="Engine"
                  value={cfg["stt_engine"] ?? "whisper"}
                  options={[
                    { value: "whisper", label: "Whisper (faster-whisper)" },
                    { value: "vosk", label: "Vosk" },
                  ]}
                  onChange={(v) => updateCfg("stt_engine", v)}
                />
                <SelectInput
                  label="Model"
                  value={cfg["stt_model"] ?? "medium"}
                  options={[
                    { value: "tiny", label: "Tiny" },
                    { value: "base", label: "Base" },
                    { value: "small", label: "Small" },
                    { value: "medium", label: "Medium" },
                    { value: "large", label: "Large" },
                  ]}
                  onChange={(v) => updateCfg("stt_model", v)}
                />
                <TextInput
                  label="Language"
                  value={cfg["stt_language"] ?? "auto"}
                  onChange={(v) => updateCfg("stt_language", v)}
                />
                {cfg["stt_engine"] === "vosk" && (
                  <TextInput
                    label="Vosk Model Path"
                    value={cfg["vosk_model_path"] ?? ""}
                    onChange={(v) => updateCfg("vosk_model_path", v)}
                  />
                )}
                <Separator />
                <SectionTitle>Text-to-Speech</SectionTitle>
                <SelectInput
                  label="Engine"
                  value={cfg["tts_engine"] ?? "edge"}
                  options={[
                    { value: "edge", label: "Edge TTS" },
                    { value: "kokoro", label: "Kokoro (offline)" },
                    { value: "elevenlabs", label: "ElevenLabs" },
                  ]}
                  onChange={(v) => updateCfg("tts_engine", v)}
                />
                <TextInput
                  label="Voice ID"
                  value={cfg["tts_voice"] ?? "af_heart"}
                  onChange={(v) => updateCfg("tts_voice", v)}
                />
                <SelectInput
                  label="Speed"
                  value={cfg["tts_speed"] ?? "1.0"}
                  options={[
                    { value: "0.8", label: "0.8x" },
                    { value: "1.0", label: "1.0x" },
                    { value: "1.2", label: "1.2x" },
                    { value: "1.5", label: "1.5x" },
                  ]}
                  onChange={(v) => updateCfg("tts_speed", v)}
                />
                <Separator />
                <SectionTitle>LLM</SectionTitle>
                <SelectInput
                  label="Provider"
                  value={cfg["llm_provider"] ?? "gemini"}
                  options={[
                    { value: "gemini", label: "Gemini" },
                    { value: "openrouter", label: "OpenRouter" },
                    { value: "ollama", label: "Ollama" },
                  ]}
                  onChange={(v) => updateCfg("llm_provider", v)}
                />
                <TextInput
                  label="Model"
                  value={cfg["llm_model"] ?? ""}
                  onChange={(v) => updateCfg("llm_model", v)}
                />
                <TextInput
                  label="Custom URL"
                  value={cfg["llm_url"] ?? ""}
                  onChange={(v) => updateCfg("llm_url", v)}
                />
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 px-4 py-3 border-t border-sirius-border">
          <button
            onClick={handleSave}
            className="text-[10px] font-mono font-bold px-3 py-1.5 rounded bg-sirius-pri text-sirius-bg hover:brightness-110 transition-all"
          >
            Save & Close
          </button>
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-sirius-text text-[10px] font-mono font-bold uppercase tracking-wider">
      {children}
    </p>
  );
}

function Separator() {
  return <hr className="border-sirius-border my-2" />;
}

function ApiKeyInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <label className="text-sirius-text-dim text-[10px] font-mono block mb-1">
        <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 ${value ? "bg-green-400" : "bg-sirius-text-dim"}`} />
        {label}
      </label>
      <div className="flex items-center gap-1">
        <input
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 bg-sirius-bg border border-sirius-border rounded px-2 py-1 text-xs font-mono text-sirius-text outline-none focus:border-sirius-pri transition-colors placeholder:text-sirius-text-dim"
        />
        <button
          onClick={() => setShow(!show)}
          className="text-[10px] text-sirius-text-dim hover:text-sirius-white px-1"
        >
          {show ? "hide" : "show"}
        </button>
      </div>
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="text-sirius-text-dim text-[10px] font-mono block mb-1">
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-sirius-bg border border-sirius-border rounded px-2 py-1 text-xs font-mono text-sirius-text outline-none focus:border-sirius-pri transition-colors"
      />
    </div>
  );
}

function SelectInput({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="text-sirius-text-dim text-[10px] font-mono block mb-1">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-sirius-bg border border-sirius-border rounded px-2 py-1 text-xs font-mono text-sirius-text outline-none focus:border-sirius-pri transition-colors appearance-none cursor-pointer"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <label className="text-sirius-text-dim text-[10px] font-mono">
        {label}
      </label>
      <button
        onClick={() => onChange(!value)}
        className={`w-8 h-4 rounded-full transition-colors relative ${
          value ? "bg-sirius-pri" : "bg-sirius-border"
        }`}
      >
        <span
          className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all ${
            value ? "left-4" : "left-0.5"
          }`}
        />
      </button>
    </div>
  );
}

export default SettingsModal;
