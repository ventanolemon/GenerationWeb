import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import "./styles/global.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element not found");
}

// HashRouter, а не BrowserRouter: фронт раздаётся как статика любым
// сервером (Nginx / ASP.NET UseStaticFiles / wwwroot) без гарантии
// history-fallback на index.html. Hash-маршруты работают везде и не 404-ят
// при обновлении/диплинке — это «надёжно» из требований.
createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <HashRouter>
        <App />
      </HashRouter>
    </ErrorBoundary>
  </StrictMode>,
);
