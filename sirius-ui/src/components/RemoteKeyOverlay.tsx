import { useState, useEffect } from "react";

interface RemoteKeyOverlayProps {
  onClose: () => void;
  qrDataUrl?: string | null;
  remoteKey?: string | null;
  loginUrl?: string;
  loading?: boolean;
  error?: string | null;
  onRequestKey?: () => void;
}

function RemoteKeyOverlay({
  onClose,
  qrDataUrl: _qrDataUrl,
  remoteKey: _remoteKey,
  loginUrl: _loginUrl,
  loading: _loading,
  error: _error,
  onRequestKey,
}: RemoteKeyOverlayProps) {
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [remoteKey, setRemoteKey] = useState<string | null>(null);
  const [loginUrl, setLoginUrl] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (_qrDataUrl) setQrDataUrl(_qrDataUrl);
    if (_remoteKey) setRemoteKey(_remoteKey);
    if (_loginUrl) setLoginUrl(_loginUrl);
    if (_loading !== undefined) setLoading(_loading);
    if (_error !== undefined) setError(_error);
  }, [_qrDataUrl, _remoteKey, _loginUrl, _loading, _error]);

  useEffect(() => {
    if (onRequestKey) onRequestKey();
  }, []);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-[380px] bg-sirius-panel border border-sirius-border rounded-lg shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-sirius-border">
          <h3 className="text-sirius-text font-inter font-bold text-xs uppercase tracking-wider">
            Remote Control
          </h3>
          <button
            onClick={onClose}
            className="text-sirius-text-dim hover:text-sirius-white text-xs transition-colors"
          >
            X
          </button>
        </div>

        <div className="p-5 flex flex-col items-center gap-4">
          {/* QR Code */}
          <div className="w-40 h-40 bg-sirius-bg border border-sirius-border rounded flex items-center justify-center overflow-hidden">
            {loading ? (
              <span className="text-sirius-text-dim text-[10px] font-mono">
                Generating...
              </span>
            ) : error ? (
              <div className="text-center p-2">
                <p className="text-sirius-red text-[9px] font-mono mb-1">Error</p>
                <p className="text-sirius-text-dim text-[7px] font-mono">{error}</p>
              </div>
            ) : qrDataUrl ? (
              <img
                src={qrDataUrl}
                alt="QR Code"
                className="block"
                width={160}
                height={160}
              />
            ) : (
              <button
                onClick={onRequestKey}
                className="text-sirius-text-dim text-xs font-mono hover:text-sirius-white transition-colors"
              >
                Generate Key
              </button>
            )}
          </div>

          {/* Key */}
          {remoteKey && (
            <div className="text-center">
              <p className="text-sirius-text-dim text-[10px] font-mono mb-1">
                Manual key:
              </p>
              <p className="text-sirius-text font-mono font-bold text-2xl tracking-[0.2em] select-all">
                {remoteKey}
              </p>
            </div>
          )}

          <p className="text-sirius-text-dim text-[8px] font-mono text-center">
            Scan the QR code or enter the key at{" "}
            <span className="text-sirius-pri break-all">{loginUrl || "..."}</span>
          </p>
        </div>
      </div>
    </div>
  );
}

export default RemoteKeyOverlay;
