import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";

export interface WsMessage {
  type: string;
  [key: string]: unknown;
}

export type LogEntry = {
  text: string;
  tag: "you" | "ai" | "err" | "file" | "sys";
};

export type AssistantState =
  | "LISTENING"
  | "THINKING"
  | "SPEAKING"
  | "PROCESSING"
  | "INITIALISING"
  | "SLEEPING"
  | "MUTED";

export type PermissionItem = {
  key: string;
  label: string;
  description: string;
  granted: boolean;
};

const WS_URL = "ws://127.0.0.1:8765";

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const onboardingCompletedRef = useRef(false);  // tracks if onboarding completed this session
  const retryCountRef = useRef(0);
  const [connected, setConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [state, setState_] = useState<AssistantState>("INITIALISING");
  const [voiceLevel, setVoiceLevel] = useState(0);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [muted, setMuted_] = useState(false);
  const [permissionRequest, setPermissionRequest] = useState<{
    perm_key: string;
    label: string;
    tool_name: string;
  } | null>(null);
  const [startupInfo, setStartupInfo] = useState<{
    action: string;
    key?: string;
    text?: string;
    current?: number;
    total?: number;
  }>({ action: "show" });
  const [notification, setNotification] = useState<string | null>(null);
  const [remoteKeyData, setRemoteKeyData] = useState<{
    url: string;
    key: string;
    login_url: string;
    manual: string;
    qr_data_url?: string;
  } | null>(null);
  const [remoteKeyError, setRemoteKeyError] = useState<string | null>(null);
  const [config, setConfig] = useState<Record<string, string> | null>(null);

  const [onboardingNeeded, setOnboardingNeeded] = useState(false);
  const [onboardingStep, setOnboardingStep] = useState<string>("");
  const [onboardingConfig, setOnboardingConfig] = useState<Record<string, string>>({});
  const [permissionsList, setPermissionsList] = useState<PermissionItem[]>([]);
  const onboardingCheckTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [radarLog, setRadarLog] = useState<string[]>([]);
  const [radarResults, setRadarResults] = useState<Record<string, unknown>[]>([]);

  const [googleConnected, setGoogleConnected] = useState(false);
  const [googleAuthMsg, setGoogleAuthMsg] = useState<string | null>(null);
  const [googleAuthLoading, setGoogleAuthLoading] = useState(false);

  const [cameraFrame, setCameraFrame] = useState<string | null>(null);
  const [audioBins, setAudioBins] = useState<{ bins: number[]; source: string } | null>(null);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const [briefing, setBriefing] = useState<{ greeting: string; headlines: string[] } | null>(null);
  const [contentPanel, setContentPanel] = useState<{ title: string; text: string } | null>(null);

  const onCommandRef = useRef<((text: string) => void) | null>(null);
  const configResolveRef = useRef<((cfg: Record<string, string>) => void) | null>(null);

  const tagFromText = (text: string): LogEntry["tag"] => {
    const lower = text.toLowerCase();
    if (lower.startsWith("you:")) return "you";
    if (lower.startsWith("sirius:")) return "ai";
    if (lower.startsWith("file:")) return "file";
    if (lower.includes("err")) return "err";
    return "sys";
  };

  const send = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  const sendCommand = useCallback(
    (text: string) => send({ type: "command", text }),
    [send]
  );

  const sendPermissionResponse = useCallback(
    (result: "once" | "always" | "deny") => {
      send({ type: "permission_response", result });
      setPermissionRequest(null);
    },
    [send]
  );

  const setMuted = useCallback(
    (v: boolean) => {
      setMuted_(v);
      send({ type: "mute_toggle", muted: v });
    },
    [send]
  );

  const fetchConfig = useCallback((): Promise<Record<string, string>> => {
    return new Promise((resolve) => {
      configResolveRef.current = resolve;
      send({ type: "get_config" });
      setTimeout(() => {
        configResolveRef.current = null;
        resolve({});
      }, 5000);
    });
  }, [send]);

  const saveConfig = useCallback(
    (payload: Record<string, unknown>, secrets: Record<string, string>, permissions?: Record<string, boolean>) => {
      const msg: Record<string, unknown> = { type: "save_config", payload, secrets };
      if (permissions) {
        msg.permissions = permissions;
      }
      send(msg);
    },
    [send]
  );

  const sendOnboarding = useCallback(
    (cfgData: Record<string, unknown>, secrets: Record<string, string>, perms: Record<string, boolean>) => {
      send({ type: "save_onboarding", config: cfgData, secrets, permissions: perms });
    },
    [send]
  );

  const sendOnboardingDone = useCallback(() => {
    onboardingCompletedRef.current = true;
    send({ type: "onboarding_done" });
    setOnboardingNeeded(false);
  }, [send]);

  const fetchPermissionsList = useCallback((): Promise<PermissionItem[]> => {
    return new Promise((resolve) => {
      const handler = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data) as WsMessage;
          if (data.type === "permissions_list") {
            window.removeEventListener("message", handler as unknown as EventListener);
            resolve((data.permissions as PermissionItem[]) ?? []);
          }
        } catch { /* ignore */ }
      };
      window.addEventListener("message", handler as unknown as EventListener);
      send({ type: "get_permissions_list" });
      setTimeout(() => {
        window.removeEventListener("message", handler as unknown as EventListener);
        resolve([]);
      }, 5000);
    });
  }, [send]);

  useEffect(() => {
    let running = true;
    const CONNECTION_TIMEOUT = 10000;
    const MAX_RETRIES = 15;

    const connect = () => {
      if (!running) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      const timeoutId = setTimeout(() => {
        ws.close();
        setConnectionError("Timeout ao conectar com o servidor.");
      }, CONNECTION_TIMEOUT);

      ws.onopen = () => {
        clearTimeout(timeoutId);
        if (!running) { ws.close(); return; }
        retryCountRef.current = 0;
        setConnectionError(null);
        setConnected(true);
        // Proactively request onboarding status — don't rely only on push
        ws.send(JSON.stringify({ type: "get_onboarding_status" }));
        // Request permissions list
        ws.send(JSON.stringify({ type: "get_permissions_list" }));
        // Request config
        ws.send(JSON.stringify({ type: "get_config" }));
        // Send current window visibility (important for autostart background)
        try { getCurrentWindow().isVisible().then(v => ws.send(JSON.stringify({ type: "set_visibility", visible: v }))); } catch {}
        clearTimeout(onboardingCheckTimer.current);
        onboardingCheckTimer.current = setTimeout(() => {
          ws.send(JSON.stringify({ type: "get_onboarding_status" }));
        }, 5000);
      };

      ws.onclose = () => {
        clearTimeout(timeoutId);
        if (!running) return;
        setConnected(false);
        retryCountRef.current++;
        if (retryCountRef.current >= MAX_RETRIES) {
          setConnectionError("Não foi possível conectar ao servidor após várias tentativas.");
          return;
        }
        reconnectTimer.current = setTimeout(connect, 2000);
      };

      ws.onerror = () => ws.close();

      ws.onmessage = (event) => {
        if (!running) return;
        try {
          const data = JSON.parse(event.data) as WsMessage;
          handleMessage(data);
        } catch { /* ignore */ }
      };
    };

    const handleMessage = (data: WsMessage) => {
      switch (data.type) {
        case "log": {
          const text = String(data.text ?? "");
          const tag = tagFromText(text);
          setLogs((prev) => [...prev, { text, tag }]);
          break;
        }
        case "state": {
          const s = String(data.state ?? "LISTENING");
          if (s === "MUTED") {
            setMuted_(true);
          } else {
            setState_(s as AssistantState);
          }
          break;
        }
        case "voice_level": {
          setVoiceLevel(Number(data.level ?? 0));
          break;
        }
        case "audio_bins": {
          setAudioBins({ bins: data.bins as number[], source: data.source as string });
          break;
        }
        case "muted": {
          setMuted_(Boolean(data.muted));
          break;
        }
        case "permission_request": {
          setPermissionRequest({
            perm_key: String(data.perm_key ?? ""),
            label: String(data.label ?? ""),
            tool_name: String(data.tool_name ?? ""),
          });
          break;
        }
        case "startup": {
          setStartupInfo({
            action: String(data.action ?? ""),
            key: data.key ? String(data.key) : undefined,
            text: data.text ? String(data.text) : undefined,
            current: typeof data.current === "number" ? data.current : undefined,
            total: typeof data.total === "number" ? data.total : undefined,
          });
          break;
        }
        case "notification": {
          setNotification(String(data.text ?? ""));
          break;
        }
        case "remote_key": {
          setRemoteKeyData({
            url: String(data.url ?? ""),
            key: String(data.key ?? ""),
            login_url: String(data.login_url ?? ""),
            manual: String(data.manual ?? ""),
            qr_data_url: data.qr_data_url ? String(data.qr_data_url) : undefined,
          });
          break;
        }
        case "remote_key_error": {
          setRemoteKeyError(String(data.message ?? "Dashboard unavailable"));
          setRemoteKeyData(null);
          break;
        }
        case "config": {
          setConfig(data as unknown as Record<string, string>);
          if (configResolveRef.current) {
            configResolveRef.current(data as unknown as Record<string, string>);
            configResolveRef.current = null;
          }
          break;
        }
        case "config_saved": {
          break;
        }
        case "onboarding_needed": {
          if (onboardingCompletedRef.current) break;  // ignore if already completed
          clearTimeout(onboardingCheckTimer.current);
          setOnboardingStep(String(data.step ?? "mode"));
          setOnboardingConfig((data.config as Record<string, string>) ?? {});
          setOnboardingNeeded(true);
          break;
        }
        case "onboarding_status": {
          clearTimeout(onboardingCheckTimer.current);
          if (data.needed === true && !onboardingCompletedRef.current) {
            setOnboardingStep(String(data.step ?? "mode"));
            setOnboardingConfig((data.config as Record<string, string>) ?? {});
            setOnboardingNeeded(true);
          }
          break;
        }
        case "permissions_list": {
          const list = (data.permissions as PermissionItem[]) ?? [];
          setPermissionsList(list);
          break;
        }
        case "radar_log":
          setRadarLog((prev) => [...prev, String(data.text ?? "")]);
          break;
        case "radar_results":
          setRadarResults((data.jobs as Record<string, unknown>[]) ?? []);
          break;
        case "radar_scanning":
          setRadarLog([]);
          setRadarResults([]);
          break;
        case "onboarding_saved": {
          onboardingCompletedRef.current = true;
          if (data.ok === true) {
            // Auto-complete: save succeeded, now mark onboarding done
            send({ type: "onboarding_done" });
          } else {
            // Save failed — log error and close wizard anyway to avoid stuck state
            const errMsg = data.error ? String(data.error) : "Unknown error";
            setLogs((prev) => [...prev, { text: `ERR: Onboarding save failed — ${errMsg}`, tag: "err" }]);
            setNotification(`Onboarding save failed: ${errMsg}. You can reconfigure in Settings.`);
            send({ type: "onboarding_done" });
          }
          setOnboardingNeeded(false);
          break;
        }
        case "hide_interface":
            getCurrentWindow().hide().catch(() => {});
            break;
        case "close_app":
            invoke("exit_app").catch(() => {});
            break;
        case "onboarding_done_ack":
        case "pong":
          break;
        case "camera_frame":
          setCameraFrame(String(data.image ?? null));
          break;
        case "camera_stop":
          setCameraFrame(null);
          break;
        case "proactive_suggestion":
          setSuggestion(String(data.text ?? null));
          break;
        case "briefing":
          setBriefing({
            greeting: String(data.greeting ?? ""),
            headlines: Array.isArray(data.headlines) ? data.headlines.map(String) : [],
          });
          break;
        case "content_panel":
          setContentPanel({ title: String(data.title ?? ""), text: String(data.text ?? "") });
          break;
        case "google_status":
          setGoogleConnected(Boolean(data.connected));
          break;
        case "google_auth_result":
          setGoogleAuthLoading(false);
          setGoogleAuthMsg(String(data.msg ?? ""));
          if (data.ok === true) {
            setGoogleConnected(true);
          }
          break;
      }
    };

    connect();

    return () => {
      running = false;
      clearTimeout(reconnectTimer.current);
      clearTimeout(onboardingCheckTimer.current);
      wsRef.current?.close();
    };
  }, []);

  const reconnect = useCallback(() => {
    retryCountRef.current = 0;
    setConnectionError(null);
    clearTimeout(reconnectTimer.current);
    wsRef.current?.close();
  }, []);

  const checkGoogleStatus = useCallback(() => {
    send({ type: "get_google_status" });
  }, [send]);

  const runGoogleAuth = useCallback(() => {
    setGoogleAuthMsg(null);
    setGoogleAuthLoading(true);
    send({ type: "google_auth" });
  }, [send]);

  return {
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
    clearNotification: () => setNotification(null),
    remoteKeyData,
    remoteKeyError,
    clearRemoteKeyError: () => setRemoteKeyError(null),
    sendCommand,
    send,
    onCommandRef,
    config,
    fetchConfig,
    saveConfig,
    onboardingNeeded,
    onboardingStep,
    onboardingConfig,
    permissionsList,
    sendOnboarding,
    sendOnboardingDone,
    fetchPermissionsList,
    radarLog,
    radarResults,
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
    clearContentPanel: () => setContentPanel(null),
    clearSuggestion: () => setSuggestion(null),
    clearBriefing: () => setBriefing(null),
    clearCameraFrame: () => setCameraFrame(null),
  };
}
