import type { Config } from "tailwindcss";

// Bahasa desain baru (2026-10-06): mengikuti bahasa desain UniFi
// Design Center (design.ui.com) — permukaan terang bersih, kartu
// putih berbatas halus, sidebar navy gelap, aksen biru konsol
// (#006fff), tipografi Inter, radius besar dan bayangan sangat
// lembut. Token "brand" dipertahankan namanya agar seluruh halaman
// yang sudah memakai kelas brand-* ikut berubah tanpa edit massal.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef6ff",
          100: "#d9eaff",
          200: "#bcdbff",
          300: "#8ec4ff",
          400: "#59a3ff",
          500: "#3385fc",
          600: "#006fff",
          700: "#0059d6",
          800: "#0049ad",
          900: "#0a2a5e",
        },
        ink: {
          700: "#1d3f6e",
          800: "#12294d",
          900: "#0a1e3c",
          950: "#060f24",
        },
        mist: "#f4f6fa",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          '"Segoe UI"',
          "Roboto",
          '"Helvetica Neue"',
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16, 24, 40, 0.05), 0 1px 3px rgba(16, 24, 40, 0.04)",
        pop: "0 12px 32px -8px rgba(6, 15, 36, 0.18), 0 4px 12px -4px rgba(6, 15, 36, 0.10)",
        glow: "0 0 0 4px rgba(0, 111, 255, 0.15)",
      },
      borderRadius: {
        "4xl": "2rem",
      },
    },
  },
  plugins: [],
};

export default config;
