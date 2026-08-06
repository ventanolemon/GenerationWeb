using System.Text.Json;

namespace WebLayer.Contracts;

/// <summary>
/// Тело POST /generate.
///
/// Параметров ГЕНЕРАЦИИ с фронта по-прежнему не приходит: всё, что нужно,
/// лежит в БД (generation_parametrs) и подтягивается FastAPI. А вот
/// параметры ПРОХОЖДЕНИЯ — приходят: одно и то же задание в тренировке и
/// в зачёте живёт по-разному, и это свойство сессии, а не раздела.
///
/// Interactive=false по умолчанию сознательно: прикрепление спецификации
/// ответа к генератору не должно менять поведение уже работающих вызовов.
/// SessionMode — только practice_free и practice; ДЗ и зачёт FastAPI
/// отвергает с 400, потому что им нужна дисциплина выдачи, которой нет.
/// </summary>
public record GenerateRequest(
    int PartitionId,
    string? UserId = null,
    bool Interactive = false,
    string SessionMode = "practice_free",
    int? MaxAttempts = null);

/// <summary>
/// Тело POST /interactive/submit — ответ пользователя в активной сессии.
///
/// Ответ приходит ЛИБО строкой (UserInput), либо по полям (Values) —
/// второе для виджета, у которого полей несколько. Склеивать поля в
/// строку на клиенте нельзя: значение со знаком равенства или точкой с
/// запятой сломало бы разбор на стороне ядра, то есть корректность
/// ответа зависела бы от того, какие символы в нём встретились.
///
/// Tolerant — разрешить мелкие опечатки (расстояние Левенштейна ≤ 1 / ≤ 2);
/// относится только к старым сессиям тренажёра слов.
/// </summary>
public record SubmitRequest(
    string SessionId,
    string UserInput = "",
    bool Tolerant = false,
    Dictionary<string, string>? Values = null);

/// <summary>
/// Тело POST /api/answers/preview — «что примут» для преподавателя.
///
/// Спецификация приходит целиком, а не по partition_id: тумблер строгости
/// крутят над ещё не сохранённым заданием, и требовать сохранения ради
/// предпросмотра значило бы сделать его бесполезным там, где он нужен.
/// Spec — сырой JSON: его структура принадлежит ядру (AnswerSpec.to_dict),
/// и дублировать её типами здесь означало бы чинить веб-слой при каждом
/// новом виде ответа.
/// </summary>
public record AnswerPreviewRequest(JsonElement Spec, string? Mode = null);

/// <summary>
/// Тело POST /export — параметры пакетной генерации в .docx.
/// </summary>
public record ExportRequest(int PartitionId, int Count = 1, bool WithAnswers = true);

/// <summary>
/// Тело POST /api/auth/login.
/// </summary>
public record LoginRequest(string Login, string Password);

/// <summary>
/// Тело POST /api/auth/register.
/// </summary>
public record RegisterRequest(
    string Login,
    string Password,
    string Fio,
    string Group = "",
    string Email = "");

/// <summary>
/// Тело PATCH /api/auth/profile/{login}.
/// </summary>
public record UpdateProfileRequest(
    string Fio,
    string Group = "",
    string Email = "",
    string About = "",
    string AvatarColor = "");

/// <summary>
/// Тело POST /api/auth/change-password.
/// </summary>
public record ChangePasswordRequest(
    string Login,
    string CurrentPassword,
    string NewPassword);

/// <summary>
/// Тело POST /api/partitions — создание или обновление раздела.
/// GenerationParams — произвольный JSON (group list, test config, fisic config).
/// </summary>
public record UpsertPartitionRequest(
    int SubjectId,
    string Name,
    int Constracted,
    object? GenerationParams = null);
