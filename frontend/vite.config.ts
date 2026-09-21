import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端「门牌」是可配置的：前端只认路径（/api、/health），不认端口，
// 所以换后端入口不需要改任何前端代码，只要改这个 target。
//
//   默认        http://localhost:8000   ← stdlib 门：backend/ 下 `python run.py`
//   切 FastAPI  http://localhost:8090   ← FastAPI 门：backend/ 下 `uvicorn app.main:app --reload --port 8090`
//
// 切换方式：在 frontend/.env.local 里写一行（该文件不进版本库）
//   VITE_API_TARGET=http://localhost:8090
// Vite 检测到 .env.local 变化会自动重启，不用手动 kill。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_TARGET || 'http://localhost:8000'

  return {
    plugins: [vue()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
        },
        // /health 不在 /api 前缀下，但 api/index.ts 的 health() 直接请求它，
        // 且 nginx.conf 也为它单独配了 location —— dev 下必须同样代理，
        // 否则请求会命中 SPA fallback 返回 index.html，health() 解析 JSON 失败，
        // 页面右上角永远显示「后端未连接（先在 backend/ 运行 python run.py）」。
        '/health': {
          target,
          changeOrigin: true,
        },
      },
    },
  }
})
