import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { serviceWorkerPlugin } from './sw-plugin.ts'

export default defineConfig({
  plugins: [react(), serviceWorkerPlugin()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
