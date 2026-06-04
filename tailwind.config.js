/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        tf: {
          bg: "#f2f2f2",
          panel: "#ffffff",
          surface: "#ffffff",
          elevated: "#f7f7f7",
          border: "#dcdcdc",
          "border-light": "#e8e8e8",
          accent: "#f59e0b",
          "accent-hover": "#d97706",
          "accent-muted": "#fef3c7",
        },
        category: {
          convert: "#3daee9",
          preprocess: "#6cc04a",
          llm: "#9b59b6",
          output: "#e8a028",
          util: "#95a5a6",
        },
        port: {
          file: "#4a90d9",
          text: "#2ecc71",
          table: "#e8a028",
          image: "#e74c8b",
          list: "#1abc9c",
          any: "#95a5a6",
        },
      },
      fontFamily: {
        sans: [
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "system-ui",
          "Segoe UI",
          "sans-serif",
        ],
        mono: ["Consolas", "JetBrains Mono", "monospace"],
      },
      boxShadow: {
        node: "0 1px 4px rgba(0,0,0,0.10), 0 1px 2px rgba(0,0,0,0.06)",
        "node-hover": "0 4px 12px rgba(0,0,0,0.10), 0 2px 4px rgba(0,0,0,0.06)",
        "node-selected": "0 0 0 2px #f59e0b, 0 4px 12px rgba(0,0,0,0.08)",
        panel: "0 1px 3px rgba(0,0,0,0.06)",
      },
      animation: {
        flow: "flow 2s linear infinite",
      },
      keyframes: {
        flow: {
          "0%": { strokeDashoffset: "24" },
          "100%": { strokeDashoffset: "0" },
        },
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
