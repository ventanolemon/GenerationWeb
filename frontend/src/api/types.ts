// Зеркало контракта ASP.NET / FastAPI. Поля приходят в snake_case (как из
// FastAPI), C#-слой их не перепаковывает в camelCase — это сознательно,
// иначе пришлось бы городить настройки JsonSerializer и поддерживать в синхроне.
// Поэтому в TypeScript мы держим именно те имена полей, что в JSON.

// ─── Блоки ────────────────────────────────────────────────────────────────
// Discriminated union по полю "type". Когда фронт встречает block.type === "text",
// TypeScript автоматически сужает тип до TextBlock и знает про поле content.
// Это даёт type-safe рендеринг без любых isinstance/switch внутри блоков.

export interface TextBlock {
  type: "text";
  content: string;
}

export interface FormulaBlock {
  type: "formula";
  latex: string;
  image_b64: string | null;
}

export interface ImageBlock {
  type: "image";
  image_b64: string | null;
  caption: string;
}

export interface CodeBlock {
  type: "code";
  code: string;
  language: string;
}

export interface TableBlock {
  type: "table";
  rows: string[][];
  header: string[] | null;
}

export interface FillInBlankBlock {
  type: "fill_in_blank";
  template: string;
  answers: string[];
  case_sensitive: boolean;
  placeholder: string;
}

export interface WordCorrectionBlock {
  type: "word_correction";
  translation: string;
  user_answer: string;
  expected: string;
  correct: boolean;
  tolerant_accept: boolean;
  diff: DiffOp[];
}

export interface DiffOp {
  op: "equal" | "replace" | "delete" | "insert";
  user: string;
  expected: string;
}

// Discriminated union из всех известных блоков. Если ядро вернёт блок
// с неизвестным "type", BlockRenderer покажет fallback (см. компонент).
export type Block =
  | TextBlock
  | FormulaBlock
  | ImageBlock
  | CodeBlock
  | TableBlock
  | FillInBlankBlock
  | WordCorrectionBlock
  // Поле "type" с произвольной строкой нужно, чтобы фронт не падал на
  // блоках, которые добавятся в ядро уже после деплоя фронта. Их мы
  // не знаем структурно, но рендерим через fallback.
  | { type: string; [key: string]: unknown };


// ─── Справочники ─────────────────────────────────────────────────────────

export interface Subject {
  id: number;
  name: string;
  parent_name: string;
}

export interface Partition {
  id: number;
  subject_id: number;
  name: string;
  constracted: number; // 0 single, 1 fisic constructor, 2 group, 3 test
  has_generator: boolean;
  view_kind: "single" | "table" | "test";
  is_interactive: boolean;
}


// ─── Ответы /generate ────────────────────────────────────────────────────
// Тоже discriminated union по type, теперь уже на уровне задания.

export interface StaticTaskResponse {
  type: "static";
  partition_id: number;
  statement: Block[];
  answer: Block[];
  meta: Record<string, unknown>;
}

export interface InteractiveStartResponse {
  type: "interactive";
  session_id: string;
  partition_id: number;
  prompt: Block[];
  is_finished: boolean;
  supports_tolerant: boolean;
}

export type GenerateResponse = StaticTaskResponse | InteractiveStartResponse;


// ─── Интерактив ──────────────────────────────────────────────────────────

export interface TurnResultResponse {
  correct: boolean;
  feedback: Block[];
  next_prompt: Block[] | null;
  is_finished: boolean;
}


// ─── Запросы ─────────────────────────────────────────────────────────────

export interface ExportRequest {
  partitionId: number;
  count: number;
  withAnswers: boolean;
}


// ─── Авторизация и профиль ────────────────────────────────────────────────

// Роль пользователя. Иерархия аддитивна: admin ⊃ teacher ⊃ student
// (та же, что в core/repository.py ROLES). Приходит из профиля FastAPI.
export type Role = "student" | "teacher" | "admin";

export interface UserInfo {
  login: string;
  fio: string;
  group: string;
  // role приходит из профиля (login/register/GET profile отдают
  // UserProfile.to_dict, где role есть всегда). Держим опциональным ради
  // обратной совместимости со старым localStorage — отсутствие трактуем
  // как "student" (наименьшие права для UX-гейтинга; сервер всё равно
  // авторитетен и вернёт 403 при попытке лишнего).
  role?: Role;
  // Расширенные поля профиля (приходят при GET /profile, могут отсутствовать при login)
  email?: string;
  about?: string;
  avatar_color?: string;
  created_at?: number;
}

export interface RegisterRequest {
  login: string;
  password: string;
  fio: string;
  group?: string;
  email?: string;
}

export interface UpdateProfileRequest {
  fio: string;
  group: string;
  email: string;
  about: string;
  avatar_color: string;
}

export interface ChangePasswordRequest {
  login: string;
  currentPassword: string;
  newPassword: string;
}


// ─── Статистика словарного тренажёра ───────────────────────────────────────

export interface WordStatEntry {
  term: string;
  translation: string;
  times_shown: number;
  times_correct: number;
  times_wrong: number;
  accuracy: number | null; // null — ни разу не отвечали
  last_seen: number;       // unix-время, 0 если не показывалось
}

export interface StatsSummary {
  total_terms: number;
  total_shown: number;
  total_correct: number;
  total_wrong: number;
  accuracy: number; // доля 0..1
}

export interface UserStats {
  is_guest: boolean;
  summary: StatsSummary;
  words: WordStatEntry[];
}


// ─── Управление разделами ─────────────────────────────────────────────────

export interface PartitionEditData {
  id: number;
  subject_id: number;
  name: string;
  constracted: number;
  generation_params: unknown;
}

export interface PartitionCandidates {
  own: Partition[];
  siblings: Partition[];
}

export interface UpsertPartitionRequest {
  subject_id: number;
  name: string;
  constracted: number;
  generation_params: unknown;
}


// ─── Аналитика (GET /analytics/overview) ───────────────────────────────────
// Форма ответа зафиксирована в core/analytics_api.py.

export interface AnalyticsTotals {
  attempts: number;
  students_active: number;
  correct_rate: number;          // доля 0..1
  tasks_active: number;
  attempts_delta_pct: number | null;   // null — нет предыдущего периода
  correct_rate_delta: number | null;   // разница долей (п.п. /100)
}

export interface TimeseriesPoint {
  date: string;      // YYYY-MM-DD (UTC)
  attempts: number;
  correct: number;
}

export interface DistributionBucket {
  bucket: string;    // "0–20%" … "80–100%"
  students: number;
}

export interface TaskStat {
  partition_id: number;
  name: string;
  subject: string;
  type: "graph" | "test";
  attempts: number;
  correct_rate: number;
  avg_attempts_to_correct: number | null;
  students: number;
  last_activity: string;   // ISO, "" если не было
  difficulty: "easy" | "medium" | "hard";
}

export interface StudentStat {
  login: string;
  fio: string;
  group: string;
  attempts: number;
  correct_rate: number;
  last_seen: string;       // ISO
  status: "struggling" | "steady" | "strong";
}

export interface GroupStat {
  group: string;
  students: number;
  correct_rate: number;
  attempts: number;
  coverage: number;        // доля 0..1
}

export interface AnalyticsOverview {
  generated_at: string;
  scope: { role: string; owner: string; range_days: number; group: string | null };
  totals: AnalyticsTotals;
  timeseries: TimeseriesPoint[];
  correctness_distribution: DistributionBucket[];
  tasks: TaskStat[];
  students: StudentStat[];
  groups: GroupStat[];
}


// ─── Администрирование (/admin/*) ──────────────────────────────────────────

export interface AdminUser {
  id: number;
  login: string;
  role: Role;
  fio: string;
  group: string;
  email: string;
  about: string;
  avatar_color: string;
  created_at: number;
}

// Группа с составом (из core/groups_api._group_dict).
export interface Group {
  id: number;
  name: string;
  created_by: string | null;
  created_at: number;
  members: string[];    // логины студентов
  teachers: string[];   // логины преподавателей
  member_count: number;
}


// ─── Домашки (/assignments/*, /groups/mine) ────────────────────────────────

export interface Assignment {
  id: number;
  partition_id: number;
  group_id: number;
  assigned_by: string | null;
  due_at: number | null;   // epoch-секунды, null — без срока
  partition_name: string;
  subject_name: string;
  group_name: string;
}

// Выдача преподавателя, обогащённая сводкой «сдали X из Y».
export interface TeachingAssignment extends Assignment {
  member_count: number;
  solved_count: number;
}

export interface AssignmentProgressStudent {
  login: string;
  fio: string;
  attempts: number;
  solved: boolean;
  last_at: number | null;
}

export interface AssignmentProgress {
  assignment: Assignment;
  students: AssignmentProgressStudent[];
  summary: { members: number; attempted: number; solved: number };
}


// ─── Контур ИИ-генерации (/contour/*) ──────────────────────────────────────
// Формы из contour_service/routers/jobs.py + core/graph_probe.py.

export type ContourStatus =
  | "queued"
  | "generating"
  | "validating"
  | "critic"
  | "awaiting_human"
  | "approved"
  | "rejected"
  | "escalated"
  | "failed";

export interface ContourJobSummary {
  job_id: string;
  status: ContourStatus;
  subject_id: number;
  description: string;
  created_at: number;
  updated_at: number;
}

export interface ProbePreview {
  seed: number;
  statement: string;
  answer: string;
}

// Один прогон probe (statement/answer — простой текст, render_plain).
export interface ProbeRun {
  seed: number;
  statement: string;
  answer: string;
  attempts: number;
  wall_ms: number;
  error: string | null;
  double_run_mismatch: boolean;
}

export interface ProbeAggregates {
  runs_ok: number;
  runs_total: number;
  distinct_statements: number;
  distinct_answers: number;
  templates: string[];
  template_count: number;
  attempts_p50: number;
  attempts_max: number;
  double_run_mismatch: boolean;
  wall_ms_max: number;
}

// Сработавший SYM-флаг (severity: "block" | "warn").
export interface ProbeFlag {
  code: string;
  severity: string;
  detail: string;
}

// Провал из вердикта критика — всегда с evidence (без него отбрасывается).
export interface CriticFailure {
  code: string;
  severity: string;
  evidence: string;
  detail?: string;
}

export interface CriticVerdict {
  verdict: "accept" | "revise" | "reject";
  confidence: number;
  summary: string;
  failures: CriticFailure[];
}

export interface ContourJobDetail extends ContourJobSummary {
  error: string | null;
  previews: ProbePreview[];
  flags: ProbeFlag[];
  probe: { runs: ProbeRun[]; aggregates: ProbeAggregates };
  critic: CriticVerdict | null;
  rounds: unknown[];
  result_graph: unknown;
}
