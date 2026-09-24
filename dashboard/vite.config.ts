import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const api = process.env.TOLLBOOTH_API ?? 'http://127.0.0.1:8080'

export default defineConfig({
  base: '/dashboard/',
  plugins: [react()],
  server: {
    proxy: {
      '/admin': api,
      '/healthz': api,
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
