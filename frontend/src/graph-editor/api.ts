// Graph-API (graph_editor_api_contract.md §2). Ходим на /api/graph/* —
// в dev Vite проксирует этот префикс прямо на generator_service (FastAPI),
// см. vite.config.ts: graph-роутер живёт там, а не в web_layer.

import type {
  Catalog,
  GraphSpecJson,
  PreviewResponse,
  ValidateResponse,
} from "./types";

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(`${path}: ${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as T;
}

export const graphApi = {
  /** Каталог — один раз при загрузке редактора; клиент с устаревшим
   * catalog_version обязан перезагрузить кеш (правило §1.3). */
  async catalog(): Promise<Catalog> {
    const resp = await fetch("/api/graph/catalog");
    if (!resp.ok) {
      throw new Error(`каталог узлов недоступен: ${resp.status}`);
    }
    return (await resp.json()) as Catalog;
  },

  validate(graph: GraphSpecJson): Promise<ValidateResponse> {
    return post<ValidateResponse>("/api/graph/validate", { graph });
  },

  preview(graph: GraphSpecJson, seeds: number[]): Promise<PreviewResponse> {
    return post<PreviewResponse>("/api/graph/preview", { graph, seeds });
  },
};
