/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // `npm run dev:live` (mode "live") talks to the real backend through the /api proxy below.
  define: mode === 'live' ? { 'import.meta.env.VITE_API_MODE': JSON.stringify('live') } : {},
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    // When the backend exists, set VITE_API_MODE=live and VITE_API_BASE_URL (or use this proxy).
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
  build: {
    target: 'es2022',
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/tests/setup.ts'],
    css: false,
    // The tests describe the built-in demo backend and its fixtures: never let a shell variable or .env file point them at a live backend.
    env: { VITE_API_MODE: 'mock' },
    // Mock latency, debounces and lazy chunks are real time; a slow or busy machine (Windows + antivirus/OneDrive, parallel workers) must not fail them.
    testTimeout: 20000,
  },
}));
