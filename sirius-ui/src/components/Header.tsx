import { useState, useEffect } from "react";
import { isWindowVisible } from "../lib/windowState";

function Header() {
  const [time, setTime] = useState("");
  const [date, setDate] = useState("");

  useEffect(() => {
    const tick = () => {
      // Keep the timer, skip the work while the window is hidden.
      if (!isWindowVisible()) return;
      const now = new Date();
      setTime(
        now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
      );
      setDate(
        now.toLocaleDateString("pt-BR", {
          weekday: "short",
          day: "numeric",
          month: "short",
        })
      );
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="flex items-center justify-between px-4 py-1.5 bg-sirius-panel border-b border-sirius-border">
      <div>
        <p className="text-sirius-text font-inter font-bold text-sm tracking-wide">
          {time}
        </p>
        <p className="text-sirius-text-dim font-inter text-[10px] uppercase tracking-wider">
          {date}
        </p>
      </div>

      {/* Right spacer */}
      <div className="w-20" />
    </header>
  );
}

export default Header;
