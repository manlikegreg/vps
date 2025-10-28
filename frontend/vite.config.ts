import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',   // Allows connections from any IP (needed for cloud hosts like Render)
    port: 5173,        // You can keep this or let Render set PORT via env
  },
  preview: {
    allowedHosts: [
      'vps-1-006o.onrender.com', // ✅ Add your Render domain here
      'localhost',               // ✅ Keep localhost for local dev
    ],
  },
})
