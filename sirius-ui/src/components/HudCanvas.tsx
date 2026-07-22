import { useRef, useEffect } from "react";

interface AudioBinsData {
  bins: number[];
  source: string;
}

interface HudCanvasProps {
  state: string;
  voiceLevel: number;
  muted: boolean;
  audioBins: AudioBinsData | null;
}

const COLOR_MAP: Record<string, string> = {
  MUTED: "#ff3366",
  SPEAKING: "#ff6b00",
  THINKING: "#ffcc00",
  PROCESSING: "#ffcc00",
  LISTENING: "#00ff88",
  INITIALISING: "#00aaff",
  SLEEPING: "#506070",
};

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace("#", "");
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  };
}

function HudCanvas({ state, voiceLevel, muted, audioBins }: HudCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const tickRef = useRef(0);
  const rafRef = useRef<number>(0);
  const prevBinsRef = useRef<number[]>([]);

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
    const color = COLOR_MAP[state] ?? "#00aaff";
    const { r, g, b } = hexToRgb(color);

    const draw = () => {
      tickRef.current++;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const W = canvas.width / (window.devicePixelRatio || 1);
      const H = canvas.height / (window.devicePixelRatio || 1);

      // Waveform bars — full width, bottom area
      const barW = 4;
      const barGap = 3;
      const barTotal = barW + barGap;
      const barCount = Math.floor(W / barTotal);
      const barMaxH = H * 0.35;
      const barY0 = H;

      // Determine which bins to use
      const bins = audioBins?.bins ?? [];
      const source = audioBins?.source ?? "";
      let useBins: number[];

      if (isSpeaking && source === "tts" && bins.length > 0) {
        useBins = bins;
      } else if (isListening && source === "mic" && bins.length > 0) {
        useBins = bins;
      } else {
        useBins = prevBinsRef.current.map((_, i) => {
          const t = tickRef.current * 0.08 + i * 0.3;
          const target = Math.sin(t) * 0.2 + 0.5;
          return prevBinsRef.current[i] * 0.92 + target * 0.08;
        });
      }

      // Smooth bins (lerp with previous frame)
      const numBins = useBins.length;
      if (prevBinsRef.current.length !== numBins) {
        prevBinsRef.current = useBins.slice();
      }
      const smoothed = useBins.map((v, i) => {
        const prev = prevBinsRef.current[i] ?? v;
        return prev * 0.7 + v * 0.3;
      });
      prevBinsRef.current = smoothed;

      for (let i = 0; i < barCount; i++) {
        let h: number;
        if (smoothed.length > 0) {
          const binIdx = (i / barCount) * smoothed.length;
          const idx0 = Math.floor(binIdx);
          const idx1 = Math.min(idx0 + 1, smoothed.length - 1);
          const frac = binIdx - idx0;
          h = smoothed[idx0] * (1 - frac) + smoothed[idx1] * frac;
        } else if (isMuted) {
          h = 0.06;
        } else {
          const t = tickRef.current * 0.08 + i * 0.3;
          h = Math.sin(t) * 0.2 + 0.5;
        }
        const barH = Math.max(1.5, h * barMaxH);
        const bx = i * barTotal;
        const by = barY0 - barH;
        const alpha = 60 + 120 * h;
        const clampedAlpha = Math.min(1, alpha / 255);
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${clampedAlpha})`;
        ctx.fillRect(bx, by, barW, barH);
      }

      // Status text — centered
      const label = muted ? "MUTED" : state;
      ctx.font = 'bold 12px "Inter", "Segoe UI", sans-serif';
      ctx.fillStyle = color;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const blink = tickRef.current % 60 < 30;
      ctx.globalAlpha =
        blink && !isSpeaking && !isListening ? 0.6 : 1;
      ctx.fillText(label, W / 2, H / 2);
      ctx.globalAlpha = 1;

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(rafRef.current);
    };
  }, [state, voiceLevel, muted, audioBins]);

  return <canvas ref={canvasRef} className="w-full h-full block" />;
}

export default HudCanvas;
