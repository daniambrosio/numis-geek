import { execSync } from 'node:child_process'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import pkg from './package.json' with { type: 'json' }

// Spec 54 — bake build version no bundle pra display + mismatch detection.
function safeGitSha(): string {
  try {
    return execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().trim()
  } catch {
    return 'unknown'
  }
}

const gitSha = process.env.GIT_SHA ?? safeGitSha()
const buildDate = process.env.BUILD_DATE ?? new Date().toISOString().slice(0, 10)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __APP_SHA__: JSON.stringify(gitSha),
    __APP_BUILD_DATE__: JSON.stringify(buildDate),
  },
  server: {
    proxy: {
      // Backend monta routers com prefix="/api" (ver app.py), então
      // proxy forward sem rewrite — o path /api/X chega como /api/X.
      '/api': 'http://localhost:8000',
    },
  },
})
