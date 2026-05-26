namespace WebLayer.Contracts;

/// <summary>
/// Тело POST /generate — клиент шлёт partition_id раздела, который хочет
/// получить. Никаких параметров генерации с фронта не приходит: всё, что
/// нужно, лежит в БД (generation_parametrs) и подтягивается FastAPI.
/// </summary>
public record GenerateRequest(int PartitionId);

/// <summary>
/// Тело POST /interactive/submit — ответ пользователя в активной сессии.
/// </summary>
public record SubmitRequest(string SessionId, string UserInput);

/// <summary>
/// Тело POST /export — параметры пакетной генерации в .docx.
/// </summary>
public record ExportRequest(int PartitionId, int Count = 1, bool WithAnswers = true);
