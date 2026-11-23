import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'
import { defineConfig } from 'vitest/config'
import { serviceWorkerPlugin } from './sw-plugin.ts'

export default defineConfig({
  plugins: [react(), serviceWorkerPlugin()],
  build: {
    rollupOptions: {
      // Вторая страница — окно стенда (Electron), без стилей и кода планшета и админки.
      input: { main: resolve(import.meta.dirname, 'index.html'), station: resolve(import.meta.dirname, 'station.html') },
    },
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
