import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const allowedHosts = (process.env.VITE_ALLOWED_PREVIEW_HOSTS || '')
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean)
  const devPort = Number(process.env.VITE_DEV_PORT || 5174)
  const previewPort = Number(process.env.VITE_PREVIEW_PORT || 5174)
  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: devPort,
    },
    preview: {
      allowedHosts,
      host: '0.0.0.0',
      port: previewPort,
    },
  }
})
