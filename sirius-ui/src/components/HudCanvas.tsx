import { useRef, useEffect } from "react";

interface HudCanvasProps {
  state: string;
  voiceLevel: number;
  muted: boolean;
}

const COLOR_MAP: Record<string, { icon: string; label: string; color: string }> =
  {
    MUTED: { icon: "M", label: "MUTED", color: "#ff3366" },
    SPEAKING: { icon: "o", label: "SPEAKING", color: "#ff6b00" },
    THINKING: { icon: "<>", label: "THINKING", color: "#ffcc00" },
    PROCESSING: { icon: ">>", label: "PROCESSING", color: "#ffcc00" },
    LISTENING: { icon: "o", label: "LISTENING", color: "#00ff88" },
    INITIALISING: { icon: "o", label: "INITIALISING", color: "#00aaff" },
    SLEEPING: { icon: "o", label: "SLEEPING", color: "#506070" },
  };

const DEFAULT_INFO = { icon: "o", label: "INITIALISING", color: "#00aaff" };

function HudCanvas({ state, voiceLevel, muted }: HudCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tickRef = useRef(0);
  const rafRef = useRef<number>(0);
  const scaleRef = useRef(1);
  const haloRef = useRef(40);

  const info = COLOR_MAP[state] ?? DEFAULT_INFO;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
    };
    resize();
    window.addEventListener("resize", resize);

    const isSpeaking = state === "SPEAKING";
    const isListening = state === "LISTENING";
    const isMuted = state === "MUTED";

    const dots: {
      angle: number;
      rFactor: number;
      baseSize: number;
      phase: number;
    }[] = [];
    for (const rf of [0.38, 0.42]) {
      const count = rf > 0.4 ? 60 : 50;
      for (let i = 0; i < count; i++) {
        dots.push({
          angle: (i / count) * Math.PI * 2,
          rFactor: rf,
          baseSize: 1.2 + Math.random() * 1.3,
          phase: Math.random() * Math.PI * 2,
        });
      }
    }

    let lastVoiceUpdate = performance.now();

    const draw = (now: number) => {
      tickRef.current++;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const W = canvas.width / (window.devicePixelRatio || 1);
      const H = canvas.height / (window.devicePixelRatio || 1);
      const cx = W / 2;
      const cy = H / 2;
      const fw = Math.min(W, H);

      // Voice-based animation updates
      if (now - lastVoiceUpdate > (isSpeaking ? 150 : 600)) {
        if (isSpeaking) {
          scaleRef.current += (1.02 + Math.random() * 0.04 - scaleRef.current) * 0.2;
          haloRef.current += (60 + Math.random() * 25 - haloRef.current) * 0.2;
        } else if (isMuted) {
          scaleRef.current += (1 - scaleRef.current) * 0.08;
          haloRef.current += (10 - haloRef.current) * 0.08;
        } else if (isListening && voiceLevel > 0.05) {
          scaleRef.current += (1 + voiceLevel * 0.15 - scaleRef.current) * 0.2;
          haloRef.current += (30 + voiceLevel * 60 - haloRef.current) * 0.2;
        } else {
          scaleRef.current += (1 - scaleRef.current) * 0.08;
          haloRef.current += (30 - haloRef.current) * 0.08;
        }
        lastVoiceUpdate = now;
      }

      // Background glow
      const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, fw * 0.5);
      const gAlpha = Math.min(1, haloRef.current / 100);
      gradient.addColorStop(0, `rgba(0, 68, 102, ${gAlpha * 0.4})`);
      gradient.addColorStop(1, "transparent");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, W, H);

      // Draw dots
      for (const dot of dots) {
        const osc = Math.sin(tickRef.current * 0.05 + dot.phase);
        let size = dot.baseSize * (1 + 0.3 * osc);
        if (isSpeaking) {
          size *= 1.2 + Math.random() * 0.6;
        } else if (isListening && voiceLevel > 0.05) {
          size *= 1 + voiceLevel * 1.5 * Math.random();
        }

        const r = fw * dot.rFactor * scaleRef.current;
        const driftAng = dot.angle + tickRef.current * 0.002;
        const dx = cx + r * Math.cos(driftAng);
        const dy = cy + r * Math.sin(driftAng);

        let alpha = 180 + 75 * osc;
        if (isMuted) alpha = Math.floor(alpha / 3);

        const dotColor =
          isListening && voiceLevel > 0.05 ? "#00ff88" : "#00aaff";
        ctx.beginPath();
        ctx.arc(dx, dy, Math.max(0.5, size), 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${hexToRgb(dotColor)}, ${Math.min(1, alpha / 255)})`;
        ctx.fill();
      }

      // Status badge
      const sy = cy - 13;
      ctx.fillStyle = "rgba(5, 5, 5, 0.6)";
      roundRect(ctx, cx - 60, sy, 120, 26, 4);
      ctx.fill();

      ctx.font = 'bold 10px "Inter", "Segoe UI", sans-serif';
      ctx.fillStyle = info.color;
      const blink = tickRef.current % 60 < 30;
      ctx.globalAlpha =
        blink && state !== "SPEAKING" && state !== "LISTENING" ? 0.6 : 1;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(`${info.icon}  ${info.label}`, cx - 50, sy + 13);
      ctx.globalAlpha = 1;

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(rafRef.current);
    };
  }, [state, voiceLevel, muted]);

  return <canvas ref={canvasRef} className="w-full h-full block" />;
}

function hexToRgb(hex: string): string {
  const v = parseInt(hex.slice(1), 16);
  return `${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}`;
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

export default HudCanvas;
