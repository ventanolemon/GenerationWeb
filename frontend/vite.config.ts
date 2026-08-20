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
      // ОТДЕЛЬНЫХ правил для /api/graph и /api/guide здесь БОЛЬШЕ НЕТ, и
      // это не упущение.
      //
      // Их роутеры живут в generator_service (там импортированы движок
      // графов и формат базы знаний), и раньше Vite ходил туда напрямую,
      // мимо web_layer. В разработке это работало, а в развёртывании —
      // нет: Vite там нет вовсе, запрос приходит в web_layer, где для
      // этих префиксов не было ни одного маршрута. Редактор графов
      // разворачивался только вместе с dev-сервером.
      //
      // Маршруты в web_layer теперь есть (GraphEndpoints, GuideEndpoints),
      // и правила отсюда убраны НАМЕРЕННО: пока они были, разработка шла
      // не тем путём, что развёртывание, и сломанный релей никто бы не
      // заметил до продакшена. Общее правило "/api" ниже отправляет их в
      // web_layer — то есть туда же, куда в бою.
      //
      // В прямом режиме (VITE_API_DIRECT=1, без .NET) то же общее правило
      // отправляет их прямо на FastAPI, так что этот режим не пострадал.
      //
      // Контур и куратор корпуса — отдельный микросервис (:8001). В прямом
      // режиме (без .NET) ходим напрямую на него со срезанным /api; в
      // обычном режиме этот блок неактивен — web_layer сам проксирует
      // /api/contour и /api/corpus дальше.
      ...(direct
        ? {
            "/api/contour": {
              target: "http://localhost:8001",
              changeOrigin: true,
              rewrite: (path: string) => path.replace(/^\/api/, ""),
            },
            "/api/corpus": {
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
