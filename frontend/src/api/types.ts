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

export interface UserInfo {
  login: string;
  fio: string;
  group: string;
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
