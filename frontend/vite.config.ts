import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import tsconfigPaths from 'vite-tsconfig-paths'

export default defineConfig({
  plugins: [
    tsconfigPaths(),
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
    tailwindcss(),
    react(),
  ],
  server: {
    host: true,
    port: 5173,
    proxy: {
      // VITE_API_TARGET=https://bots.bardsaders.com bun run dev
      // designs widgets against live data — overlay endpoints are
      // key-authed, so no session crosses over.
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:7177',
        changeOrigin: true,
      },
      '/auth': 'http://localhost:7177',
    },
  },
})
