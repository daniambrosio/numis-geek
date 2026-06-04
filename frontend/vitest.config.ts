/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
  // Spec 54 — espelha os defines do vite.config.ts pra os globals
  // bakeados (__APP_VERSION__/__APP_SHA__/__APP_BUILD_DATE__) ficarem
  // disponíveis sob o test runner.
  define: {
    __APP_VERSION__: JSON.stringify('test-version'),
    __APP_SHA__: JSON.stringify('test-sha'),
    __APP_BUILD_DATE__: JSON.stringify('2026-06-04'),
  },
})
