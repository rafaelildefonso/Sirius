import { useState, useEffect, useCallback } from "react";
import type { PermissionItem } from "../hooks/useWebSocket";
import { RotateCcw } from "./Icons";

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
  obsidianStatus?: "idle" | "connecting" | "connected" | "error";
  send?: (msg: Record<string, unknown>) => void;
}

type SettingsTab = "general" | "preferences" | "permissions" | "engines" | "plugins" | "monitores" | "integrations" | "atividade";

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
  obsidianStatus,
  send,
}: SettingsModalProps) {
  const [tab, setTab] = useState<SettingsTab>("general");
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [localPerms, setLocalPerms] = useState<Record<string, boolean>>({});

  // Plugins
  const [plugins, setPlugins] = useState<{ name: string; description: string; file: string; valid: boolean; error: string; enabled: boolean }[]>([]);
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [pluginsError, setPluginsError] = useState<string | null>(null);

  // Monitors
  const [monitors, setMonitors] = useState<string[]>([]);
  const [monitorsLoading, setMonitorsLoading] = useState(false);
  const [monitorsError, setMonitorsError] = useState<string | null>(null);
  const [newMonitorTopic, setNewMonitorTopic] = useState("");

  // Obsidian Picker
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerPath, setPickerPath] = useState("");
  const [pickerItems, setPickerItems] = useState<{ name: string; path: string }[]>([]);
  const [pickerDrives, setPickerDrives] = useState<string[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);

  // Atividade
  type ActivityDay = { day: string; minutes: number };
  type ActivityApp = { name: string; minutes: number; icon?: string };
  const [activityStats, setActivityStats] = useState<{ days: ActivityDay[]; avg_daily_minutes: number; top_apps: ActivityApp[] } | null>(null);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);

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

  const fetchPlugins = useCallback(() => {
    if (!send) return;
    setPluginsLoading(true);
    setPluginsError(null);
    const handler = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "plugins_list") {
          window.removeEventListener("message", handler);
          setPlugins(data.plugins ?? []);
          setPluginsLoading(false);
        }
      } catch { /* ignore */ }
    };
    window.addEventListener("message", handler);
    send({ type: "get_plugins_list" });
  }, [send]);

  const fetchMonitors = useCallback(() => {
    if (!send) return;
    setMonitorsLoading(true);
    setMonitorsError(null);
    const handler = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "monitors_list") {
          window.removeEventListener("message", handler);
          setMonitors(data.topics ?? []);
          setMonitorsLoading(false);
        }
      } catch { /* ignore */ }
    };
    window.addEventListener("message", handler);
    send({ type: "get_monitors_list" });
  }, [send]);

  const togglePlugin = useCallback((pluginName: string, enabled: boolean) => {
    if (!send) return;
    send({ type: "toggle_plugin", plugin_name: pluginName, enabled });
    setPlugins((prev) => prev.map((p) => (p.name === pluginName ? { ...p, enabled } : p)));
  }, [send]);

  const addMonitor = useCallback(() => {
    if (!send || !newMonitorTopic.trim()) return;
    send({ type: "add_monitor", topic: newMonitorTopic.trim() });
    setMonitors((prev) => [...prev, newMonitorTopic.trim()]);
    setNewMonitorTopic("");
  }, [send, newMonitorTopic]);

  const removeMonitor = useCallback((topic: string) => {
    if (!send) return;
    send({ type: "remove_monitor", topic });
    setMonitors((prev) => prev.filter((t) => t !== topic));
  }, [send]);

  // -- Obsidian Picker --
  const openPicker = useCallback(() => {
    if (!send) return;
    setPickerOpen(true);
    setPickerDrives([]);
    setPickerItems([]);
    setPickerLoading(true);
    const handler = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "obsidian_list_drives_ok") {
          window.removeEventListener("message", handler);
          setPickerDrives(data.drives ?? []);
          setPickerLoading(false);
        }
      } catch { /* ignore */ }
    };
    window.addEventListener("message", handler);
    send({ type: "obsidian_list_drives" });
  }, [send]);

  const navigatePicker = useCallback((path: string) => {
    if (!send) return;
    setPickerPath(path);
    setPickerLoading(true);
    setPickerItems([]);
    const handler = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "obsidian_list_children_ok") {
          window.removeEventListener("message", handler);
          setPickerItems(data.children ?? []);
          setPickerLoading(false);
        }
      } catch { /* ignore */ }
    };
    window.addEventListener("message", handler);
    send({ type: "obsidian_list_children", path });
  }, [send]);

  // -- Atividade --
  const fetchActivity = useCallback(() => {
    if (!send) return;
    setActivityLoading(true);
    setActivityError(null);
    let settled = false;
    const handler = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "activity_data") {
          settled = true;
          window.removeEventListener("message", handler);
          clearTimeout(timer);
          setActivityStats(data.stats ?? null);
          setActivityLoading(false);
        } else if (data.type === "activity_error") {
          settled = true;
          window.removeEventListener("message", handler);
          clearTimeout(timer);
          setActivityError(String(data.message ?? "Erro ao carregar dados de atividade."));
          setActivityLoading(false);
        }
      } catch { /* ignore */ }
    };
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", handler);
      setActivityLoading(false);
      setActivityError("Servidor nao respondeu (timeout).");
    }, 5000);
    window.addEventListener("message", handler);
    send({ type: "request_activity_data" });
  }, [send]);

  const toggleActivityMonitor = useCallback((enabled: boolean) => {
    if (!send) return;
    send({ type: "set_activity_monitor", enabled });
  }, [send]);

  const clearActivityData = useCallback(() => {
    if (!send) return;
    if (!window.confirm("Limpar todos os dados de atividade?")) return;
    let settled = false;
    const handler = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "activity_cleared") {
          settled = true;
          window.removeEventListener("message", handler);
          clearTimeout(timer);
          setActivityStats(null);
          setActivityError(null);
        } else if (data.type === "activity_error") {
          settled = true;
          window.removeEventListener("message", handler);
          clearTimeout(timer);
          setActivityError(String(data.message ?? "Erro ao limpar dados de atividade."));
        }
      } catch { /* ignore */ }
    };
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", handler);
      setActivityError("Servidor nao respondeu ao limpar dados.");
    }, 5000);
    window.addEventListener("message", handler);
    send({ type: "clear_activity_data" });
  }, [send]);

  // Initialize Obsidian fields from config
  useEffect(() => {
    if (!config) return;
    setCfg((prev) => ({
      ...prev,
      obsidian_vault_path: config["obsidian_vault_path"] ?? "",
      obsidian_tasks_subpath: config["obsidian_tasks_subpath"] ?? "",
      obsidian_notes_subpath: config["obsidian_notes_subpath"] ?? "",
      obsidian_sirius_subpath: config["obsidian_sirius_subpath"] ?? "",
      obsidian_task_retention_days: String(config["obsidian_task_retention_days"] ?? "30"),
    }));
  }, [config]);

  useEffect(() => {
    fetchPlugins();
    fetchMonitors();
  }, [fetchPlugins, fetchMonitors]);

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

  useEffect(() => {
    if (tab === "atividade") {
      fetchActivity();
    }
  }, [tab, fetchActivity]);

  // Sync Obsidian connection status when the integrations tab opens
  useEffect(() => {
    if (tab === "integrations") {
      send?.({ type: "get_obsidian_status" });
    }
  }, [tab, send]);

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "general", label: "General" },
    { id: "preferences", label: "Preferências" },
    { id: "permissions", label: "Permissions" },
    ...(cfg["assistant_mode"] === "local" ? [{ id: "engines" as SettingsTab, label: "Local Engines" }] : []),
    { id: "plugins" as SettingsTab, label: "Plugins" },
    { id: "monitores" as SettingsTab, label: "Monitores" },
    { id: "integrations" as SettingsTab, label: "Integrations" },
    { id: "atividade" as SettingsTab, label: "Atividade" },
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
            ) : tab === "plugins" ? (
              <div className="space-y-3">
                <SectionTitle>Plugins</SectionTitle>
                {pluginsLoading ? (
                  <p className="text-sirius-text-dim text-[10px] font-mono">Loading plugins...</p>
                ) : pluginsError ? (
                  <p className="text-sirius-red text-[10px] font-mono">{pluginsError}</p>
                ) : plugins.length === 0 ? (
                  <p className="text-sirius-text-dim text-[10px] font-mono">Nenhum plugin encontrado.</p>
                ) : (
                  <div className="space-y-2">
                    {plugins.map((plugin) => (
                      <div key={plugin.name} className="flex items-start gap-3 p-2 rounded-lg border border-sirius-border">
                        <div className="flex-1 min-w-0">
                          <p className={`text-[10px] font-mono font-bold ${plugin.valid ? "text-sirius-text" : "text-sirius-red"}`}>
                            {plugin.name}
                          </p>
                          <p className="text-sirius-text-dim text-[9px] font-mono mt-0.5">{plugin.description}</p>
                          {plugin.error && (
                            <p className="text-sirius-red text-[9px] font-mono mt-0.5">{plugin.error}</p>
                          )}
                        </div>
                        <button
                          onClick={() => togglePlugin(plugin.name, !plugin.enabled)}
                          className={`w-8 h-4 rounded-full transition-colors relative shrink-0 mt-0.5 ${plugin.enabled ? "bg-sirius-pri" : "bg-sirius-border"}`}
                        >
                          <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all ${plugin.enabled ? "left-4" : "left-0.5"}`} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : tab === "monitores" ? (
              <div className="space-y-3">
                <SectionTitle>Monitoramento Proativo</SectionTitle>
                <p className="text-sirius-text-dim text-[9px] font-mono">
                  Adicione topicos para monitoramento proativo.
                </p>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={newMonitorTopic}
                    onChange={(e) => setNewMonitorTopic(e.target.value)}
                    placeholder="Ex: clima em sao-paulo"
                    className="flex-1 bg-sirius-bg border border-sirius-border rounded px-2 py-1 text-xs font-mono text-sirius-text outline-none focus:border-sirius-pri transition-colors placeholder:text-sirius-text-dim"
                    onKeyDown={(e) => { if (e.key === "Enter") addMonitor(); }}
                  />
                  <button
                    onClick={addMonitor}
                    disabled={!newMonitorTopic.trim()}
                    className={`text-[10px] font-mono font-bold px-2 py-1 rounded transition-colors ${newMonitorTopic.trim() ? "bg-sirius-pri text-sirius-bg hover:brightness-110" : "bg-sirius-border text-sirius-text-dim cursor-not-allowed"}`}
                  >
                    + Add
                  </button>
                </div>
                {monitorsLoading ? (
                  <p className="text-sirius-text-dim text-[10px] font-mono">Loading...</p>
                ) : monitorsError ? (
                  <p className="text-sirius-red text-[10px] font-mono">{monitorsError}</p>
                ) : monitors.length === 0 ? (
                  <p className="text-sirius-text-dim text-[10px] font-mono">Nenhum monitor configurado.</p>
                ) : (
                  <div className="space-y-1">
                    {monitors.map((topic) => (
                      <div key={topic} className="flex items-center justify-between p-2 rounded border border-sirius-border">
                        <span className="text-sirius-text text-[10px] font-mono">{topic}</span>
                        <button
                          onClick={() => removeMonitor(topic)}
                          className="text-sirius-red text-[9px] font-mono hover:text-sirius-white transition-colors"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : tab === "integrations" ? (
              <div className="space-y-3">
                <SectionTitle>Obsidian Vault</SectionTitle>
                <TextInput
                  label="Caminho do Vault"
                  value={cfg["obsidian_vault_path"] ?? ""}
                  onChange={(v) => updateCfg("obsidian_vault_path", v)}
                />
                <div className="flex gap-2">
                  <button
                    onClick={openPicker}
                    className="text-[10px] font-mono font-bold px-2 py-1 rounded text-sirius-text-dim hover:text-sirius-white border border-sirius-border hover:border-sirius-pri transition-colors"
                  >
                    Procurar...
                  </button>
                  {pickerOpen && (
                    <span className="text-[9px] font-mono text-sirius-text-dim self-center">{pickerPath || "(raiz)"}</span>
                  )}
                </div>
                {obsidianStatus === "connecting" && (
                  <p className="text-sirius-text-dim text-[10px] font-mono">Conectando ao Obsidian...</p>
                )}
                {obsidianStatus === "error" && (
                  <div className="flex items-center gap-2">
                    <p className="text-sirius-red text-[10px] font-mono">Erro ao conectar ao Obsidian</p>
                    <button
                      onClick={() => send?.({ type: "obsidian_retry_connect" })}
                      title="Tentar novamente"
                      className="text-sirius-text-dim hover:text-sirius-pri border border-sirius-border hover:border-sirius-pri rounded p-1 transition-colors"
                    >
                      <RotateCcw size="sm" />
                    </button>
                  </div>
                )}
                {pickerOpen && (
                  <div className="border border-sirius-border rounded p-2 max-h-32 overflow-y-auto space-y-0.5">
                    {pickerLoading ? (
                      <p className="text-sirius-text-dim text-[9px] font-mono">Carregando...</p>
                    ) : pickerDrives.length > 0 && pickerItems.length === 0 ? (
                      pickerDrives.map((d) => (
                        <button
                          key={d}
                          onClick={() => navigatePicker(d)}
                          className="w-full text-left text-[10px] font-mono text-sirius-text hover:text-sirius-pri px-1 py-0.5 rounded hover:bg-sirius-pri-dim/10 transition-colors"
                        >
                          {d}
                        </button>
                      ))
                    ) : pickerItems.length === 0 ? (
                      <p className="text-sirius-text-dim text-[9px] font-mono">Vazio</p>
                    ) : (
                      <>
                        {pickerPath && (
                          <button
                            onClick={() => {
                              const parent = pickerPath.replace(/\\/g, "/").split("/").slice(0, -1).join("/");
                              if (parent && parent !== pickerPath) navigatePicker(parent);
                            }}
                            className="w-full text-left text-[10px] font-mono text-sirius-text-dim hover:text-sirius-white px-1 py-0.5 rounded hover:bg-sirius-pri-dim/10 transition-colors"
                          >
                            ..
                          </button>
                        )}
                        {pickerItems.map((item) => (
                          <button
                            key={item.path}
                            onClick={() => navigatePicker(item.path)}
                            className="w-full text-left text-[10px] font-mono text-sirius-text hover:text-sirius-pri px-1 py-0.5 rounded hover:bg-sirius-pri-dim/10 transition-colors"
                          >
                            {item.name}/
                          </button>
                        ))}
                      </>
                    )}
                    {!pickerLoading && pickerItems.length > 0 && (
                      <button
                        onClick={() => { updateCfg("obsidian_vault_path", pickerPath); setPickerOpen(false); }}
                        className="w-full text-left text-[10px] font-mono font-bold text-sirius-pri hover:text-sirius-white px-1 py-0.5 rounded bg-sirius-pri-dim/20 transition-colors"
                      >
                        Selecionar esta pasta
                      </button>
                    )}
                  </div>
                )}
                <TextInput label="Subpasta de Tarefas" value={cfg["obsidian_tasks_subpath"] ?? ""} onChange={(v) => updateCfg("obsidian_tasks_subpath", v)} />
                <TextInput label="Subpasta de Notas" value={cfg["obsidian_notes_subpath"] ?? ""} onChange={(v) => updateCfg("obsidian_notes_subpath", v)} />
                <TextInput label="Subpasta Sirius" value={cfg["obsidian_sirius_subpath"] ?? ""} onChange={(v) => updateCfg("obsidian_sirius_subpath", v)} />
                <Separator />
                <SectionTitle>Retenção</SectionTitle>
                <TextInput
                  label="Retencao de Tarefas (dias)"
                  value={cfg["obsidian_task_retention_days"] ?? "30"}
                  onChange={(v) => updateCfg("obsidian_task_retention_days", v)}
                />
              </div>
            ) : tab === "atividade" ? (
              <div className="space-y-3">
                <SectionTitle>Uso de Apps</SectionTitle>
                <div className="flex items-center justify-between py-1">
                  <label className="text-sirius-text-dim text-[10px] font-mono">Monitorar uso de apps</label>
                  <button
                    onClick={() => toggleActivityMonitor(cfg["activity_monitor"] !== "true")}
                    className={`w-8 h-4 rounded-full transition-colors relative ${cfg["activity_monitor"] === "true" ? "bg-sirius-pri" : "bg-sirius-border"}`}
                  >
                    <span className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all ${cfg["activity_monitor"] === "true" ? "left-4" : "left-0.5"}`} />
                  </button>
                </div>
                {activityLoading ? (
                  <p className="text-sirius-text-dim text-[10px] font-mono">Carregando...</p>
                ) : activityError ? (
                  <p className="text-sirius-red text-[10px] font-mono">{activityError}</p>
                ) : activityStats ? (
                  <div className="space-y-2">
                    <div className="space-y-1">
                      {activityStats.days.map((d) => (
                        <div key={d.day} className="flex items-center gap-2">
                          <span className="text-[9px] font-mono text-sirius-text-dim w-8 shrink-0">{d.day}</span>
                          <div className="flex-1 bg-sirius-border rounded h-2 overflow-hidden">
                            <div
                              className="h-full bg-sirius-pri rounded transition-all"
                              style={{ width: `${Math.min((d.minutes / (Math.max(...activityStats.days.map((x) => x.minutes), 1))) * 100, 100)}%` }}
                            />
                          </div>
                          <span className="text-[9px] font-mono text-sirius-text-dim w-10 text-right">{d.minutes}min</span>
                        </div>
                      ))}
                    </div>
                    <p className="text-[9px] font-mono text-sirius-text-dim">
                      Media diaria: {Math.round(activityStats.avg_daily_minutes)} min
                    </p>
                    {activityStats.top_apps.length > 0 && (
                      <div className="space-y-0.5">
                        <p className="text-[9px] font-mono text-sirius-text-dim uppercase tracking-wider">Mais usados na semana</p>
                        {activityStats.top_apps.map((app) => (
                          <div key={app.name} className="flex items-center justify-between">
                            <div className="flex items-center gap-2 min-w-0">
                              {app.icon ? (
                                <img src={app.icon} alt={app.name} className="w-3.5 h-3.5 rounded-sm shrink-0" />
                              ) : (
                                <span className="w-3.5 h-3.5 rounded-sm bg-sirius-border text-sirius-text-dim text-[8px] font-mono flex items-center justify-center shrink-0">
                                  {(app.name || "?").charAt(0).toUpperCase()}
                                </span>
                              )}
                              <span className="text-[10px] font-mono text-sirius-text truncate">{app.name}</span>
                            </div>
                            <span className="text-[9px] font-mono text-sirius-text-dim">{app.minutes}min</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <button
                      onClick={clearActivityData}
                      className="text-[10px] font-mono font-bold px-2 py-1 rounded text-sirius-red border border-sirius-red/30 hover:bg-sirius-red/10 transition-colors"
                    >
                      Limpar dados
                    </button>
                  </div>
                ) : (
                  <p className="text-sirius-text-dim text-[10px] font-mono">Nenhum dado disponivel.</p>
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
