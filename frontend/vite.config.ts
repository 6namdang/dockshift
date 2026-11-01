import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    // The FastAPI backend serves the built app under /ui/, so assets must be
    // requested from there rather than from the site root.
    base: '/ui/',
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // `npm run dev` talks to the backend on :8000 without CORS.
      proxy: {
        '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
        '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      },
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modify—file watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
  };
});
