/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        sirius: {
          bg: "#050505",
          panel: "#0c0c0c",
          panel2: "#121212",
          border: "#1a1a1a",
          border2: "#252525",
          pri: "var(--sirius-pri, #00aaff)",
          "pri-dim": "var(--sirius-pri-dim, #004466)",
          acc: "#ff6b00",
          acc2: "#ffcc00",
          green: "#00ff88",
          "green-dim": "#004422",
          red: "#ff3355",
          muted: "#ff3366",
          text: "#e0f0ff",
          "text-dim": "#506070",
          "text-med": "#8090a0",
          white: "#ffffff",
        },
      },
      fontFamily: {
        inter: ['"Inter"', '"Segoe UI"', '"Noto Sans"', "Arial", "sans-serif"],
        mono: ['"Courier New"', '"Cascadia Code"', '"Fira Code"', "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        breathe: "breathe 4s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        breathe: {
          "0%, 100%": { transform: "scale(1)", opacity: "0.7" },
          "50%": { transform: "scale(1.03)", opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};
