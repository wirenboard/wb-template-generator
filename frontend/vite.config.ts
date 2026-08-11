import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Порт бэкенда в dev — 9000 (см. docker-compose.yml и CLAUDE.md).
    // Прокси нужен, чтобы браузер ходил на тот же origin и CORS не требовался.
    proxy: {
      '/api': 'http://localhost:9000'
    }
  }
})
