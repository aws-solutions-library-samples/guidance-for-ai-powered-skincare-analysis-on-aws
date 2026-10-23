import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_')
  return {
    plugins: [react()],
    define: { global: 'globalThis' },
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: env.VITE_API_URL ? {
        '/api': {
          target: env.VITE_API_URL,
          changeOrigin: true,
          rewrite: path => path.replace(/^\/api/, ''),
        },
      } : undefined,
    },
  }
})
