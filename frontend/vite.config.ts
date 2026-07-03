import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev mode proxies API calls to the FastAPI backend (uv run python -m steam_idle_bot --web).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        ws: true,
      },
    },
  },
})
