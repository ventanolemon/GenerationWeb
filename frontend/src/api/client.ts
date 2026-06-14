// Тонкий API-клиент. Все запросы идут на /api/* — этот префикс либо
// проксируется Vite на ASP.NET (см. vite.config.ts), либо раздаётся
// тем же сервером в продакшене. Никаких "http://localhost:5000" в коде —
// это сделало бы deploy невозможным без правок.

import type {
  ChangePasswordRequest,
  ExportRequest,
  GenerateResponse,
  Partition,
  PartitionCandidates,
  PartitionEditData,
  RegisterRequest,
  Subject,
  TurnResultResponse,
  UpdateProfileRequest,
  UpsertPartitionRequest,
  UserInfo,
} from "./types";

// Базовая обёртка вокруг fetch с двумя задачами: распарсить JSON и
// дать осмысленную ошибку. ASP.NET-слой при ошибках отдаёт JSON
// { "error": "..." } — мы это поднимаем в Error.message.
class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    // Пытаемся достать { error } из тела, но не падаем, если оно пустое
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body && typeof body === "object" && "error" in body) {
        detail = String((body as { error: unknown }).error);
      }
    } catch {
      // тело не JSON или пустое — оставляем statusText
    }
    throw new ApiError(detail, response.status);
  }

  // Для 204 No Content (мы не используем, но на будущее) JSON парсить нельзя
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// ─── Публичные методы ────────────────────────────────────────────────────

export const api = {
  listSubjects(): Promise<Subject[]> {
    return request<Subject[]>("/api/subjects");
  },

  listPartitions(subjectId: number): Promise<Partition[]> {
    return request<Partition[]>(`/api/subjects/${subjectId}/partitions`);
  },

  generate(partitionId: number, userId?: string | null): Promise<GenerateResponse> {
    return request<GenerateResponse>("/api/generate", {
      method: "POST",
      body: JSON.stringify({ partitionId, userId: userId ?? null }),
    });
  },

  submit(sessionId: string, userInput: string, tolerant = false): Promise<TurnResultResponse> {
    return request<TurnResultResponse>("/api/interactive/submit", {
      method: "POST",
      body: JSON.stringify({ sessionId, userInput, tolerant }),
    });
  },

  // ─── Авторизация и профиль ────────────────────────────────────────────────

  login(login: string, password: string): Promise<UserInfo> {
    return request<UserInfo>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password }),
    });
  },

  register(body: RegisterRequest): Promise<UserInfo> {
    return request<UserInfo>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  getProfile(login: string): Promise<UserInfo> {
    return request<UserInfo>(`/api/auth/profile/${encodeURIComponent(login)}`);
  },

  updateProfile(login: string, body: UpdateProfileRequest): Promise<UserInfo> {
    return request<UserInfo>(`/api/auth/profile/${encodeURIComponent(login)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  changePassword(body: ChangePasswordRequest): Promise<void> {
    return request<void>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        login: body.login,
        current_password: body.currentPassword,
        new_password: body.newPassword,
      }),
    });
  },

  // ─── Управление разделами ──────────────────────────────────────────────

  getPartitionForEdit(id: number): Promise<PartitionEditData> {
    return request<PartitionEditData>(`/api/partitions/${id}`);
  },

  getPartitionCandidates(subjectId: number): Promise<PartitionCandidates> {
    return request<PartitionCandidates>(`/api/partitions/candidates/${subjectId}`);
  },

  upsertPartition(body: UpsertPartitionRequest): Promise<{ partition_id: number }> {
    return request<{ partition_id: number }>("/api/partitions", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  deletePartition(id: number, subjectId: number): Promise<{ deleted: number }> {
    return request<{ deleted: number }>(`/api/partitions/${id}?subjectId=${subjectId}`, {
      method: "DELETE",
    });
  },

  /**
   * Экспорт. Не парсим JSON — возвращаем сам Response,
   * чтобы вызывающий код мог сделать blob() и триггернуть download.
   */
  async export(body: ExportRequest): Promise<Blob> {
    const response = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const json = await response.json();
        if (json?.error) detail = String(json.error);
      } catch {
        /* not json */
      }
      throw new ApiError(detail, response.status);
    }
    return await response.blob();
  },
};

export { ApiError };
