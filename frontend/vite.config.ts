import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite proxy для /api сильно упрощает локальную разработку: фронт ходит
// на свой же origin (http://localhost:5173), Vite переадресует запросы
// на ASP.NET (http://localhost:5000). Это значит, что в production-сборке
// (когда фронт раздаётся тем же сервером, что и API) ничего менять не
// надо — относительные URL "/api/..." работают везде.
//
// Если ASP.NET у вас на другом порту — поменяйте target.
//
// VITE_API_DIRECT=1 — dev-режим без ASP.NET: ВЕСЬ /api проксируется прямо
// на generator_service (FastAPI, :8000) со срезанным префиксом (маршруты
// совпадают: web_layer — тонкий прокси). Удобно там, где dotnet недоступен.
const direct = process.env.VITE_API_DIRECT === "1";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Graph-роутер живёт в generator_service (FastAPI, :8000), а не в
      // web_layer — см. docs/architecture/graph_editor_api_contract.md §2.
      // Более специфичный префикс должен идти ПЕРЕД общим "/api".
      "/api/graph": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      // Контур — отдельный микросервис (:8001). В прямом режиме (без .NET)
      // ходим напрямую на него со срезанным /api; в обычном режиме этот
      // блок неактивен — web_layer сам проксирует /api/contour дальше.
      ...(direct
        ? {
            "/api/contour": {
              target: "http://localhost:8001",
              changeOrigin: true,
              rewrite: (path: string) => path.replace(/^\/api/, ""),
            },
          }
        : {}),
      "/api": direct
        ? {
            target: "http://localhost:8000",
            changeOrigin: true,
            rewrite: (path) => path.replace(/^\/api/, ""),
          }
        : {
            target: "http://localhost:5000",
            changeOrigin: true,
          },
    },
  },
});
