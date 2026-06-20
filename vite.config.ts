import { defineConfig } from 'vite'
import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // Alias @ to the src directory
      '@': path.resolve(__dirname, './src'),
    },
  },

  // File types to support raw imports. Never add .css, .tsx, or .ts files to this.
  assetsInclude: ['**/*.svg', '**/*.csv'],

  server: {
    // AuData defaults: frontend 5173, backend 8010 — chosen so the app can run
    // alongside other local services without a port clash. Override with
    // FRONTEND_PORT / BACKEND_PORT (setup.sh exports these).
    port: Number(process.env.FRONTEND_PORT) || 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_BASE_URL || `http://localhost:${process.env.BACKEND_PORT || 8010}`,
        changeOrigin: true,
      },
    },
  },
})
