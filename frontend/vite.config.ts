import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite proxy для /api сильно упрощает локальную разработку: фронт ходит
// на свой же origin (http://localhost:5173), Vite переадресует запросы
// на ASP.NET (http://localhost:5000). Это значит, что в production-сборке
// (когда фронт раздаётся тем же сервером, что и API) ничего менять не
// надо — относительные URL "/api/..." работают везде.
//
// Если ASP.NET у вас на другом порту — поменяйте target.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:5000",
        changeOrigin: true,
      },
    },
  },
});
