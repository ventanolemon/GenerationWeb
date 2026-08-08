// Тонкий API-клиент. Все запросы идут на /api/* — этот префикс либо
// проксируется Vite на ASP.NET (см. vite.config.ts), либо раздаётся
// тем же сервером в продакшене. Никаких "http://localhost:5000" в коде —
// это сделало бы deploy невозможным без правок.

import type {
  AdminUser,
  AnalyticsOverview,
  AnswerPreview,
  AnswerSpec,
  Assignment,
  AssignmentProgress,
  ChangePasswordRequest,
  ContourJobDetail,
  ContourJobSummary,
  CorpusListResponse,
  CorpusRecordDetail,
  Curation,
  ExportRequest,
  GenerateResponse,
  Group,
  MyOrganization,
  Organization,
  Partition,
  PartitionCandidates,
  PartitionEditData,
  RegisterRequest,
  Role,
  Subject,
  TeachingAssignment,
  TurnResultResponse,
  UpdateProfileRequest,
  UpsertPartitionRequest,
  UserInfo,
  UserStats,
} from "./types";

// Идентичность для RBAC-эндпоинтов (/analytics, /admin, /assignments,
// /groups). Заверяет её ТОКЕН: сервер по нему сам смотрит, кто это и какая
// у него роль. X-User-Id / X-User-Role остаются на время перехода (их ещё
// шлёт десктоп) и перестанут что-либо значить, когда на сервере снимут
// GEN_TRUST_IDENTITY_HEADERS. Слать роль как заявление — ровно то, из-за
// чего преподаватель мог назначить себя админом.
export interface Identity {
  login: string;
  role?: Role;
  token?: string;
}

function idHeaders(id: Identity): Record<string, string> {
  const headers: Record<string, string> = {
    "X-User-Id": id.login,
    "X-User-Role": id.role ?? "student",
  };
  if (id.token) headers["Authorization"] = `Bearer ${id.token}`;
  return headers;
}

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

  // Параметры прохождения (не генерации): одно и то же задание в
  // тренировке и в зачёте живёт по-разному. interactive=false по
  // умолчанию — появление спецификации ответа у генератора не должно
  // менять поведение уже работающих экранов.
  generate(
    partitionId: number,
    userId?: string | null,
    session?: { interactive?: boolean; sessionMode?: string; maxAttempts?: number },
  ): Promise<GenerateResponse> {
    return request<GenerateResponse>("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        partitionId,
        userId: userId ?? null,
        interactive: session?.interactive ?? false,
        sessionMode: session?.sessionMode ?? "practice_free",
        maxAttempts: session?.maxAttempts ?? null,
      }),
    });
  },

  submit(sessionId: string, userInput: string, tolerant = false): Promise<TurnResultResponse> {
    return request<TurnResultResponse>("/api/interactive/submit", {
      method: "POST",
      body: JSON.stringify({ sessionId, userInput, tolerant }),
    });
  },

  // Ответ по полям — для виджета, у которого их несколько. Склеивать
  // поля в строку здесь нельзя: значение со знаком равенства или точкой
  // с запятой сломало бы разбор на стороне ядра.
  submitValues(
    sessionId: string,
    values: Record<string, string>,
  ): Promise<TurnResultResponse> {
    return request<TurnResultResponse>("/api/interactive/submit", {
      method: "POST",
      body: JSON.stringify({ sessionId, userInput: "", values }),
    });
  },

  // «Что примут» — материал ПРЕПОДАВАТЕЛЯ, поэтому отдельный запрос, а не
  // поле в ответе /generate: для выражения он стоит около 200 мс, и
  // платить их на каждой генерации ради подсказки, которую смотрят раз
  // при настройке, незачем.
  previewAnswer(spec: AnswerSpec, mode?: string): Promise<AnswerPreview> {
    return request<AnswerPreview>("/api/answers/preview", {
      method: "POST",
      body: JSON.stringify({ spec, mode: mode ?? null }),
    });
  },

  // ─── Авторизация и профиль ────────────────────────────────────────────────

  login(login: string, password: string): Promise<UserInfo> {
    return request<UserInfo>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password }),
    });
  },

  // Выход гасит сессию на сервере, а не только забывает её в браузере.
  // Ошибку глотаем: пользователь всё равно выходит локально, и держать его
  // в приложении из-за недоступной сети было бы хуже.
  async logout(id: Identity): Promise<void> {
    try {
      await request<void>("/api/auth/logout", {
        method: "POST",
        headers: idHeaders(id),
      });
    } catch {
      /* сессия истечёт сама по expires_at */
    }
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

  // Требует identity: сервер пускает владельца профиля и админа. Раньше
  // проверки не было вовсе — чужой профиль правился без единого заголовка.
  updateProfile(
    id: Identity,
    login: string,
    body: UpdateProfileRequest,
  ): Promise<UserInfo> {
    return request<UserInfo>(`/api/auth/profile/${encodeURIComponent(login)}`, {
      method: "PATCH",
      headers: idHeaders(id),
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

  // ─── Статистика ────────────────────────────────────────────────────────────

  getStats(userId: string): Promise<UserStats> {
    return request<UserStats>(`/api/stats?userId=${encodeURIComponent(userId)}`);
  },

  // ─── Управление разделами ──────────────────────────────────────────────

  // Чтение устройства раздела тоже требует identity: это эндпоинт
  // РЕДАКТОРА, а не витрины. Сервис авторизует его скоупом выдач — 401 без
  // identity, 403 студенту (generation_params помогают угадывать ответы),
  // 404 на чужой предмет. Витрина (getSubjects, getPartitions) не тронута:
  // она отдаёт имена, и по ней ходит гость.
  getPartitionForEdit(
    identity: Identity,
    id: number,
  ): Promise<PartitionEditData> {
    return request<PartitionEditData>(`/api/partitions/${id}`, {
      headers: idHeaders(identity),
    });
  },

  getPartitionCandidates(
    identity: Identity,
    subjectId: number,
  ): Promise<PartitionCandidates> {
    return request<PartitionCandidates>(
      `/api/partitions/candidates/${subjectId}`,
      { headers: idHeaders(identity) },
    );
  },

  // Мутации разделов требуют identity: сервис авторизует их тем же
  // правилом, что и push синхронизации, — нужна роль teacher/admin, и чужой
  // предмет на запись недоступен (403). Гость сюда не ходит, поэтому
  // Identity обязателен, а не опционален: пропущенный заголовок дал бы 401
  // и выглядел бы «сервер сломался», хотя сломан был бы вызов.
  upsertPartition(
    identity: Identity,
    body: UpsertPartitionRequest,
  ): Promise<{ partition_id: number }> {
    return request<{ partition_id: number }>("/api/partitions", {
      method: "POST",
      headers: idHeaders(identity),
      body: JSON.stringify(body),
    });
  },

  deletePartition(
    identity: Identity,
    id: number,
    subjectId: number,
  ): Promise<{ deleted: number }> {
    return request<{ deleted: number }>(`/api/partitions/${id}?subjectId=${subjectId}`, {
      method: "DELETE",
      headers: idHeaders(identity),
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

  // ─── Аналитика (RBAC — teacher/admin) ────────────────────────────────────

  analyticsOverview(
    id: Identity,
    opts: { rangeDays?: number; group?: string | null } = {},
  ): Promise<AnalyticsOverview> {
    const q = new URLSearchParams();
    if (opts.rangeDays) q.set("range_days", String(opts.rangeDays));
    if (opts.group) q.set("group", opts.group);
    const qs = q.toString();
    return request<AnalyticsOverview>(
      `/api/analytics/overview${qs ? `?${qs}` : ""}`,
      { headers: idHeaders(id) },
    );
  },

  // ─── Администрирование (RBAC — admin) ────────────────────────────────────

  adminListUsers(id: Identity): Promise<{ users: AdminUser[] }> {
    return request<{ users: AdminUser[] }>("/api/admin/users", {
      headers: idHeaders(id),
    });
  },

  // ─── Организации (§8) ───────────────────────────────────────────────

  myOrganization(id: Identity): Promise<MyOrganization> {
    return request<MyOrganization>("/api/organizations/mine", {
      headers: idHeaders(id),
    });
  },

  adminListOrganizations(
    id: Identity,
  ): Promise<{ organizations: Organization[] }> {
    return request("/api/admin/organizations", { headers: idHeaders(id) });
  },

  adminGetOrganization(id: Identity, orgId: number): Promise<Organization> {
    return request(`/api/admin/organizations/${orgId}`, {
      headers: idHeaders(id),
    });
  },

  adminCreateOrganization(
    id: Identity,
    name: string,
    parentId: number | null = null,
  ): Promise<Organization> {
    return request("/api/admin/organizations", {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ name, parent_id: parentId }),
    });
  },

  adminRenameOrganization(
    id: Identity,
    orgId: number,
    name: string,
  ): Promise<Organization> {
    return request(`/api/admin/organizations/${orgId}`, {
      method: "PATCH",
      headers: idHeaders(id),
      body: JSON.stringify({ name }),
    });
  },

  adminAddToOrganization(
    id: Identity,
    orgId: number,
    login: string,
  ): Promise<{ login: string; organization_id: number | null }> {
    return request(`/api/admin/organizations/${orgId}/members`, {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ login }),
    });
  },

  adminRemoveFromOrganization(
    id: Identity,
    orgId: number,
    login: string,
  ): Promise<{ login: string; organization_id: number | null }> {
    return request(
      `/api/admin/organizations/${orgId}/members/${encodeURIComponent(login)}`,
      { method: "DELETE", headers: idHeaders(id) },
    );
  },

  adminTransferOwnership(
    id: Identity,
    orgId: number,
    login: string,
  ): Promise<Organization> {
    return request(`/api/admin/organizations/${orgId}/owner`, {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ login }),
    });
  },

  adminSetSuperuser(
    id: Identity,
    login: string,
    isSuperuser: boolean,
  ): Promise<{ login: string; is_superuser: boolean }> {
    return request(`/api/admin/superusers/${encodeURIComponent(login)}`, {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ is_superuser: isSuperuser }),
    });
  },

  adminChangeRole(
    id: Identity,
    login: string,
    role: Role,
  ): Promise<{ login: string; role: Role }> {
    return request(`/api/admin/users/${encodeURIComponent(login)}/role`, {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ role }),
    });
  },

  adminListGroups(id: Identity): Promise<{ groups: Group[] }> {
    return request<{ groups: Group[] }>("/api/admin/groups", {
      headers: idHeaders(id),
    });
  },

  adminCreateGroup(id: Identity, name: string): Promise<Group> {
    return request<Group>("/api/admin/groups", {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ name }),
    });
  },

  adminAddMember(id: Identity, groupId: number, login: string): Promise<Group> {
    return request<Group>(`/api/admin/groups/${groupId}/members`, {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ login }),
    });
  },

  adminRemoveMember(id: Identity, groupId: number, login: string): Promise<Group> {
    return request<Group>(
      `/api/admin/groups/${groupId}/members/${encodeURIComponent(login)}`,
      { method: "DELETE", headers: idHeaders(id) },
    );
  },

  adminAssignTeacher(id: Identity, groupId: number, login: string): Promise<Group> {
    return request<Group>(`/api/admin/groups/${groupId}/teachers`, {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ login }),
    });
  },

  adminUnassignTeacher(id: Identity, groupId: number, login: string): Promise<Group> {
    return request<Group>(
      `/api/admin/groups/${groupId}/teachers/${encodeURIComponent(login)}`,
      { method: "DELETE", headers: idHeaders(id) },
    );
  },

  // ─── Домашки (/assignments, /groups/mine) ────────────────────────────────

  groupsMine(id: Identity): Promise<{ groups: Group[] }> {
    return request<{ groups: Group[] }>("/api/groups/mine", {
      headers: idHeaders(id),
    });
  },

  createAssignment(
    id: Identity,
    body: { partition_id: number; group_id: number; due_at?: number | null },
  ): Promise<Assignment> {
    return request<Assignment>("/api/assignments", {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify(body),
    });
  },

  teachingAssignments(id: Identity): Promise<{ assignments: TeachingAssignment[] }> {
    return request<{ assignments: TeachingAssignment[] }>(
      "/api/assignments/teaching",
      { headers: idHeaders(id) },
    );
  },

  assignmentProgress(id: Identity, assignmentId: number): Promise<AssignmentProgress> {
    return request<AssignmentProgress>(
      `/api/assignments/${assignmentId}/progress`,
      { headers: idHeaders(id) },
    );
  },

  myAssignments(id: Identity): Promise<{ assignments: Assignment[] }> {
    return request<{ assignments: Assignment[] }>("/api/assignments/mine", {
      headers: idHeaders(id),
    });
  },

  deleteAssignment(id: Identity, assignmentId: number): Promise<{ deleted: number }> {
    return request<{ deleted: number }>(`/api/assignments/${assignmentId}`, {
      method: "DELETE",
      headers: idHeaders(id),
    });
  },

  // ─── Контур ИИ-генерации (/contour/*, teacher/admin) ─────────────────────

  contourListJobs(id: Identity): Promise<{ jobs: ContourJobSummary[] }> {
    return request<{ jobs: ContourJobSummary[] }>("/api/contour/jobs", {
      headers: idHeaders(id),
    });
  },

  contourGetJob(id: Identity, jobId: string): Promise<ContourJobDetail> {
    return request<ContourJobDetail>(
      `/api/contour/jobs/${encodeURIComponent(jobId)}`,
      { headers: idHeaders(id) },
    );
  },

  contourCreateJob(
    id: Identity,
    body: { description: string; subject_id: number; constraints?: Record<string, unknown> },
  ): Promise<{ job_id: string; status: string }> {
    return request<{ job_id: string; status: string }>("/api/contour/jobs", {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify(body),
    });
  },

  contourApprove(
    id: Identity,
    jobId: string,
    body: { partition_name?: string; note?: string },
  ): Promise<{ job_id: string; status: string; partition_id: number; corpus_deduplicated: boolean }> {
    return request(`/api/contour/jobs/${encodeURIComponent(jobId)}/approve`, {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify(body),
    });
  },

  contourReject(
    id: Identity,
    jobId: string,
    reason: string,
  ): Promise<{ job_id: string; status: string }> {
    return request(`/api/contour/jobs/${encodeURIComponent(jobId)}/reject`, {
      method: "POST",
      headers: idHeaders(id),
      body: JSON.stringify({ reason }),
    });
  },

  // ─── Куратор корпуса (/corpus/*, admin) ──────────────────────────────────

  corpusList(
    id: Identity,
    opts: { curation?: Curation; kind?: "generate" | "repair" } = {},
  ): Promise<CorpusListResponse> {
    const q = new URLSearchParams();
    if (opts.curation) q.set("curation", opts.curation);
    if (opts.kind) q.set("kind", opts.kind);
    const qs = q.toString();
    return request<CorpusListResponse>(`/api/corpus${qs ? `?${qs}` : ""}`, {
      headers: idHeaders(id),
    });
  },

  corpusGet(id: Identity, recordId: string): Promise<CorpusRecordDetail> {
    return request<CorpusRecordDetail>(
      `/api/corpus/${encodeURIComponent(recordId)}`,
      { headers: idHeaders(id) },
    );
  },

  corpusSetCuration(
    id: Identity,
    recordId: string,
    body: { curation: Curation; comment?: string },
  ): Promise<{ record_id: string; curation: Curation }> {
    return request(`/api/corpus/${encodeURIComponent(recordId)}/curation`, {
      method: "PATCH",
      headers: idHeaders(id),
      body: JSON.stringify(body),
    });
  },
};

export { ApiError };
