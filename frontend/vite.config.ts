import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev (`npm run dev`) API calls are proxied to the FastAPI server on :8765.
// In production `npm run build` writes dist/, which FastAPI serves at /.
const api = 'http://localhost:8765'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/auth': api,
      '/devices': api,
      '/scenes': api,
      '/core': api,
      '/ws': { target: api, ws: true },
    },
  },
})
