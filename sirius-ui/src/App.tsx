import { useState, useCallback, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useWebSocket } from "./hooks/useWebSocket";
import HudCanvas from "./components/HudCanvas";
import LogPanel from "./components/LogPanel";
import SettingsModal from "./components/SettingsModal";
import StartupPanel from "./components/StartupPanel";
import PermissionDialog from "./components/PermissionDialog";
import FileDropZone from "./components/FileDropZone";
import RemoteKeyOverlay from "./components/RemoteKeyOverlay";
import RadarPanel from "./components/RadarPanel";
import CameraPreview from "./components/CameraPreview";
import SuggestionCard from "./components/SuggestionCard";
import Header from "./components/Header";
import Footer from "./components/Footer";
import OnboardingWizard from "./components/OnboardingWizard";
import { Send, Mic, MicOff, Monitor, Maximize, Square } from "./components/Icons";
import ContentPanel from "./components/ContentPanel";
import ClipboardPanel from "./components/ClipboardPanel";

function App() {
  const {
    connected,
    connectionError,
    reconnect,
    state,
    voiceLevel,
    logs,
    muted,
    setMuted,
    permissionRequest,
    sendPermissionResponse,
    startupInfo,
    notification,
    clearNotification,
    remoteKeyData,
    remoteKeyError,
    clearRemoteKeyError,
    sendCommand,
    config,
    saveConfig,
    onboardingNeeded,
    onboardingStep,
    onboardingConfig,
    permissionsList,
    sendOnboarding,
    sendOnboardingDone,
    radarLog,
    radarResults,
    send,
    googleConnected,
    googleAuthMsg,
    googleAuthLoading,
    checkGoogleStatus,
    runGoogleAuth,
    cameraFrame,
    audioBins,
    suggestion,
    briefing,
    contentPanel,
    clearContentPanel,
    clearSuggestion,
    clearBriefing,
    clearCameraFrame,
  } = useWebSocket();

  const [view, setView] = useState<"hud" | "radar">("hud");
  const [showSettings, setShowSettings] = useState(false);
  const [showRemote, setShowRemote] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [textInput, setTextInput] = useState("");
  const [filePath, setFilePath] = useState<string | null>(null);
  const [autoStart, setAutoStart] = useState(false);

  const handleOpenRemote = useCallback(() => {
    clearRemoteKeyError();
    setShowRemote(true);
    send({ type: "request_remote_key" });
  }, [send, clearRemoteKeyError]);

  const handleSend = useCallback(() => {
    const t = textInput.trim();
    if (!t) return;
    sendCommand(t);
    setTextInput("");
  }, [textInput, sendCommand]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleToggleMute = useCallback(() => {
    setMuted(!muted);
  }, [muted, setMuted]);

  const handleInterrupt = useCallback(() => {
    send({ type: "interrupt" });
  }, [send]);

  const toggleFullscreen = useCallback(() => {
    setFullscreen((v) => !v);
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, []);

  // Listen for fullscreen changes
  useEffect(() => {
    const onFs = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  // Load autostart state on mount
  useEffect(() => {
    invoke<boolean>("is_autostart_enabled")
      .then(setAutoStart)
      .catch(() => {});
  }, []);

  // Apply UI color from config
  useEffect(() => {
    const color = config?.["ui_color"];
    if (color) {
      document.documentElement.style.setProperty("--sirius-pri", color);
      // Derive a dimmed version
      document.documentElement.style.setProperty("--sirius-pri-dim", color + "44");
    }
  }, [config]);

  const handleSetAutoStart = useCallback((enabled: boolean) => {
    invoke("set_autostart", { enabled }).catch(() => {});
    setAutoStart(enabled);
  }, []);

  // Update tray tooltip with startup progress
  useEffect(() => {
    const prefix = "SIRIUS";
    let text = "";
    if (startupInfo.action === "progress" && typeof startupInfo.current === "number" && typeof startupInfo.total === "number") {
      text = `${prefix} — [${startupInfo.current}/${startupInfo.total}] ${startupInfo.text ?? "..."}`;
    } else if (startupInfo.action === "hide") {
      text = `${prefix} — AI Assistant`;
    } else if (startupInfo.action === "ready") {
      text = `${prefix} — ${startupInfo.key ?? "component"} pronto`;
    } else if (startupInfo.action === "error") {
      text = `${prefix} — Erro: ${startupInfo.text ?? startupInfo.key ?? "unknown"}`;
    } else if (startupInfo.action === "status" || startupInfo.action === "show") {
      text = `${prefix} — ${startupInfo.text ?? "Iniciando..."}`;
    }
    if (text) {
      invoke("update_tray_tooltip", { text }).catch(() => {});
    }
  }, [startupInfo]);

  // F4 to toggle mute, Escape to interrupt, F11 for fullscreen
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F4") {
        e.preventDefault();
        handleToggleMute();
      } else if (e.key === "Escape") {
        e.preventDefault();
        handleInterrupt();
      } else if (e.key === "F11") {
        e.preventDefault();
        toggleFullscreen();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleToggleMute, toggleFullscreen, handleInterrupt]);

  // Listen for Tauri tray events and forward to backend
  useEffect(() => {
    const unlistenMute = listen("toggle-mute", () => {
      send({ type: "toggle_mute" });
    });
    const unlistenShown = listen("window-shown", () => {
      send({ type: "set_visibility", visible: true });
    });
    const unlistenHidden = listen("window-hidden", () => {
      send({ type: "set_visibility", visible: false });
    });
    return () => {
      unlistenMute.then((f) => f());
      unlistenShown.then((f) => f());
      unlistenHidden.then((f) => f());
    };
  }, [send]);

  // Auto-hide notification
  useEffect(() => {
    if (notification) {
      const t = setTimeout(clearNotification, 4000);
      return () => clearTimeout(t);
    }
  }, [notification, clearNotification]);

  // Auto-dismiss suggestion after 15s
  useEffect(() => {
    if (suggestion) {
      const t = setTimeout(clearSuggestion, 15000);
      return () => clearTimeout(t);
    }
  }, [suggestion, clearSuggestion]);

  const handleDismissBriefing = useCallback(() => {
    send({ type: "briefing_dismissed" });
    clearBriefing();
  }, [send, clearBriefing]);

  if (connectionError) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-sirius-bg select-none">
        <div className="bg-sirius-panel border border-sirius-border rounded-lg p-8 text-center max-w-md mx-4">
          <h2 className="text-sirius-red text-lg font-bold mb-3">Erro de Conexao</h2>
          <p className="text-sirius-text-dim text-sm mb-6">{connectionError}</p>
          <p className="text-sirius-text-dim text-xs mb-4">Verifique se o backend SIRIUS esta em execucao.</p>
          <button
            onClick={reconnect}
            className="bg-sirius-pri hover:bg-sirius-pri/80 text-white font-bold px-6 py-2 rounded transition-colors cursor-pointer"
          >
            Tentar Novamente
          </button>
        </div>
      </div>
    );
  }

  if (onboardingNeeded) {
    return (
      <OnboardingWizard
        initialStep={onboardingStep}
        initialConfig={onboardingConfig}
        permissions={permissionsList}
        onSave={sendOnboarding}
        onDone={sendOnboardingDone}
      />
    );
  }

  return (
    <div className="w-full h-full flex flex-col bg-sirius-bg select-none">
      {/* Header */}
      <Header />

      {/* Notification toast */}
      {notification && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 animate-slide-up">
          <div className="bg-sirius-panel2 border border-sirius-border rounded-lg px-4 py-2 shadow-lg">
            <p className="text-sirius-text-dim text-xs">{notification}</p>
          </div>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left — HUD or Job Radar */}
        <div className="flex-1 relative">
          {view === "hud" ? (
            <HudCanvas
              state={muted ? "MUTED" : state}
              voiceLevel={voiceLevel}
              muted={muted}
              audioBins={audioBins}
            />
          ) : (
            <RadarPanel
              sendMessage={send}
              radarLog={radarLog}
              radarResults={radarResults}
            />
          )}

          {/* Content panel for news, search results, etc. */}
          {contentPanel && (
            <ContentPanel
              title={contentPanel.title}
              text={contentPanel.text}
              onDismiss={clearContentPanel}
            />
          )}

          {/* Camera preview overlay */}
          <CameraPreview frame={cameraFrame} onClose={clearCameraFrame} />

          {/* Connection indicator */}
          {!connected && (
            <div className="absolute top-3 left-3 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-sirius-red animate-pulse" />
              <span className="text-sirius-red text-xs font-mono">
                DISCONNECTED
              </span>
            </div>
          )}
        </div>

        {/* Right panel */}
        <div
          className="w-[340px] min-w-[340px] flex flex-col bg-sirius-panel border-l border-sirius-border"
        >
          {/* Log */}
          <LogPanel logs={logs} />

          {/* File drop */}
          <FileDropZone onFileChange={setFilePath} />

          {/* Input */}
          <div className="flex items-center gap-2 px-2 py-1.5 border-t border-sirius-border">
            <input
              type="text"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a command..."
              className="flex-1 bg-transparent text-sirius-text text-sm font-inter px-2 py-1.5 outline-none placeholder:text-sirius-text-dim"
            />
            <button
              onClick={handleSend}
              className="text-sirius-pri hover:text-sirius-white transition-colors px-2"
              title="Send"
            >
              <Send />
            </button>
          </div>

          {/* Bottom buttons */}
          <div className="flex items-center gap-1 px-2 py-1 border-t border-sirius-border">
            {/* Mute */}
            <button
              onClick={handleToggleMute}
              className={`text-xs font-mono font-bold px-2 py-1 rounded transition-colors flex items-center gap-1 ${
                muted
                  ? "text-sirius-muted bg-sirius-muted/10"
                  : "text-sirius-text-dim hover:text-sirius-white"
              }`}
              title={muted ? "Unmute" : "Mute"}
            >
              {muted ? <MicOff size="sm" /> : <Mic size="sm" />}
              <span>{muted ? "MUTED" : "LIVE"}</span>
            </button>

            {/* Interrupt / Stop */}
            <button
              onClick={handleInterrupt}
              className="text-xs font-mono font-bold px-2 py-1 rounded text-sirius-red hover:text-sirius-white hover:bg-sirius-red/20 transition-colors flex items-center gap-1"
              title="Interromper [ESC]"
            >
              <Square size="sm" />
              <span>STOP</span>
            </button>

            <div className="flex-1" />

            {/* Remote Control */}
            <button
              onClick={handleOpenRemote}
              className="text-xs font-mono font-bold px-2 py-1 rounded text-sirius-text-dim hover:text-sirius-white transition-colors flex items-center gap-1"
              title="Remote Control"
            >
              <Monitor size="sm" />
              <span>Remote</span>
            </button>

            {/* Fullscreen */}
            <button
              onClick={toggleFullscreen}
              className="text-xs font-mono font-bold px-2 py-1 rounded text-sirius-text-dim hover:text-sirius-white transition-colors flex items-center gap-1"
              title="Fullscreen"
            >
              <Maximize size="sm" />
              <span>FS</span>
            </button>
          </div>
        </div>
      </div>

      {/* Suggestion card */}
      <SuggestionCard text={suggestion} onDismiss={clearSuggestion} />

      {/* Clipboard intelligence */}
      <ClipboardPanel sendCommand={sendCommand} />

      {/* Footer */}
      <Footer
        view={view}
        onViewChange={setView}
        onSettingsClick={() => setShowSettings(true)}
        muted={muted}
      />

      {/* Overlays */}
      {showSettings && (
        <SettingsModal
          onClose={() => setShowSettings(false)}
          config={config}
          onSaveConfig={saveConfig}
          permissions={permissionsList}
          autoStart={autoStart}
          onSetAutoStart={handleSetAutoStart}
          googleConnected={googleConnected}
          googleAuthMsg={googleAuthMsg}
          googleAuthLoading={googleAuthLoading}
          onCheckGoogleStatus={checkGoogleStatus}
          onRunGoogleAuth={runGoogleAuth}
          send={send}
        />
      )}

      {showRemote && (
        <RemoteKeyOverlay
          onClose={() => setShowRemote(false)}
          qrDataUrl={remoteKeyData?.qr_data_url}
          remoteKey={remoteKeyData?.key ?? null}
          loginUrl={remoteKeyData?.login_url}
          loading={!remoteKeyData && !remoteKeyError}
          error={remoteKeyError}
          onRequestKey={() => send({ type: "request_remote_key" })}
        />
      )}

      {permissionRequest && (
        <PermissionDialog
          label={permissionRequest.label}
          toolName={permissionRequest.tool_name}
          onResponse={sendPermissionResponse}
        />
      )}

      {(startupInfo.action !== "hide" || briefing) && (
        <StartupPanel
          action={startupInfo.action}
          componentKey={startupInfo.key}
          statusText={startupInfo.text}
          current={startupInfo.current}
          total={startupInfo.total}
          onComplete={() => {}}
          briefing={briefing}
          onDismissBriefing={handleDismissBriefing}
        />
      )}
    </div>
  );
}

export default App;
