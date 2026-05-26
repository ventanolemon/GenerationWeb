namespace WebLayer.Contracts;

/// <summary>
/// Тело POST /generate — клиент шлёт partition_id раздела, который хочет
/// получить. Никаких параметров генерации с фронта не приходит: всё, что
/// нужно, лежит в БД (generation_parametrs) и подтягивается FastAPI.
/// </summary>
public record GenerateRequest(int PartitionId);

/// <summary>
/// Тело POST /interactive/submit — ответ пользователя в активной сессии.
/// Tolerant — разрешить мелкие опечатки (расстояние Левенштейна ≤ 1 / ≤ 2).
/// </summary>
public record SubmitRequest(string SessionId, string UserInput, bool Tolerant = false);

/// <summary>
/// Тело POST /export — параметры пакетной генерации в .docx.
/// </summary>
public record ExportRequest(int PartitionId, int Count = 1, bool WithAnswers = true);

/// <summary>
/// Тело POST /api/auth/login.
/// </summary>
public record LoginRequest(string Login, string Password);

/// <summary>
/// Тело POST /api/partitions — создание или обновление раздела.
/// GenerationParams — произвольный JSON (group list, test config, fisic config).
/// </summary>
public record UpsertPartitionRequest(
    int SubjectId,
    string Name,
    int Constracted,
    object? GenerationParams = null);
