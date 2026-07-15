import { Settings } from "./Icons";

type View = "hud" | "radar";

interface FooterProps {
  view: View;
  onViewChange: (v: View) => void;
  onSettingsClick: () => void;
  muted: boolean;
}

function Footer({ view, onViewChange, onSettingsClick, muted }: FooterProps) {
  return (
    <footer className="flex items-center justify-between px-3 py-1 bg-sirius-panel border-t border-sirius-border">
      {/* View toggle */}
      <div className="flex items-center gap-1">
        <button
          onClick={() => onViewChange("hud")}
          className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded transition-colors ${
            view === "hud"
              ? "text-sirius-pri bg-sirius-pri-dim/20"
              : "text-sirius-text-dim hover:text-sirius-white"
          }`}
        >
          HUD
        </button>
        <button
          onClick={() => onViewChange("radar")}
          className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded transition-colors ${
            view === "radar"
              ? "text-sirius-pri bg-sirius-pri-dim/20"
              : "text-sirius-text-dim hover:text-sirius-white"
          }`}
        >
          RADAR
        </button>
      </div>

      {/* Center: Mute status */}
      <div className="flex items-center gap-1">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            muted
              ? "bg-sirius-muted"
              : "bg-sirius-green"
          }`}
        />
        <span className="text-[10px] font-mono text-sirius-text-dim">
          {muted ? "MUTED" : "LIVE"}
        </span>
      </div>

      {/* Settings gear */}
      <button
        onClick={onSettingsClick}
        className="text-sirius-text-dim hover:text-sirius-white transition-colors px-2"
        title="Settings"
      >
        <Settings />
      </button>
    </footer>
  );
}

export default Footer;
