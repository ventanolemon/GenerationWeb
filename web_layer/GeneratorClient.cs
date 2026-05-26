using System.Net.Http.Json;
using System.Text.Json;
using WebLayer.Contracts;

namespace WebLayer.Services;

/// <summary>
/// Типизированный клиент к FastAPI generator_service.
///
/// Регистрируется как Typed HttpClient в Program.cs — это даёт:
///   * единый BaseAddress из конфига,
///   * единый Timeout,
///   * включение в HttpClientFactory (что важно: предотвращает утечку
///     сокетов через короткоживущие HttpClient'ы).
///
/// Сам клиент сознательно тонкий. Никакого маппинга блоков — наружу
/// отдаём либо строго типизированные обёртки (subjects, partitions,
/// turn result), либо сырой JsonElement (статичные задачи, экспорт).
/// </summary>
public sealed class GeneratorClient
{
    private readonly HttpClient _http;
    private readonly ILogger<GeneratorClient> _log;

    // Один общий JsonSerializerOptions на инстанс — создавать его в каждом
    // запросе дороже и приводит к ненужному прогреву кешей рефлексии.
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public GeneratorClient(HttpClient http, ILogger<GeneratorClient> log)
    {
        _http = http;
        _log = log;
    }

    // ─── Справочники ───────────────────────────────────────────────────

    public async Task<List<SubjectDto>> ListSubjectsAsync(CancellationToken ct)
    {
        var subjects = await _http.GetFromJsonAsync<List<SubjectDto>>(
            "/subjects", JsonOptions, ct);
        return subjects ?? new List<SubjectDto>();
    }

    public async Task<List<PartitionDto>?> ListPartitionsAsync(int subjectId, CancellationToken ct)
    {
        // Здесь нужно различать 404 (нет предмета) и ошибку сети — поэтому
        // не используем GetFromJsonAsync, который бросит исключение на 404.
        var response = await _http.GetAsync($"/subjects/{subjectId}/partitions", ct);
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<List<PartitionDto>>(JsonOptions, ct)
               ?? new List<PartitionDto>();
    }

    // ─── Генерация ─────────────────────────────────────────────────────

    /// <summary>
    /// Сырой результат /generate.
    ///
    /// Возвращаем JsonElement, потому что FastAPI отдаёт либо
    /// StaticTaskResponse, либо InteractiveStartResponse — два разных
    /// объекта одного маршрута. Разбирать sum-тип через discriminator
    /// "type" чище на уровне эндпоинта, чем здесь.
    ///
    /// Бросает HttpRequestException при 5xx, возвращает null при 404
    /// (нет генератора для этого partition_id).
    /// </summary>
    public async Task<JsonElement?> GenerateAsync(int partitionId, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/generate", new { partition_id = partitionId }, ct);

        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return null;
        }

        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<JsonElement>(JsonOptions, ct);
    }

    // ─── Интерактив ────────────────────────────────────────────────────

    public async Task<(TurnResultResponse? Result, bool SessionExists)> SubmitAsync(
        string sessionId, string userInput, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/interactive/submit",
            new { session_id = sessionId, user_input = userInput },
            ct);

        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return (null, false);
        }

        response.EnsureSuccessStatusCode();
        var result = await response.Content.ReadFromJsonAsync<TurnResultResponse>(JsonOptions, ct);
        return (result, true);
    }

    // ─── Экспорт ───────────────────────────────────────────────────────

    /// <summary>
    /// Скачивает .docx из FastAPI и возвращает поток. Поток нужно
    /// либо передать в Results.File (это делает Endpoint), либо
    /// явно задиспозить.
    ///
    /// Возвращает null при 404, бросает при прочих ошибках.
    /// </summary>
    public async Task<(Stream? Body, string? FileName)> ExportAsync(
        ExportRequest request, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/export",
            new
            {
                partition_id = request.PartitionId,
                count = request.Count,
                with_answers = request.WithAnswers
            },
            ct);

        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return (null, null);
        }
        if (response.StatusCode == System.Net.HttpStatusCode.BadRequest)
        {
            // Например, попытка экспортировать интерактивный раздел
            var detail = await response.Content.ReadAsStringAsync(ct);
            throw new HttpRequestException(
                $"Bad request from generator service: {detail}",
                inner: null,
                statusCode: System.Net.HttpStatusCode.BadRequest);
        }

        response.EnsureSuccessStatusCode();
        var fileName = response.Content.Headers.ContentDisposition?.FileName?.Trim('"')
                       ?? $"tasks_{request.PartitionId}.docx";
        var body = await response.Content.ReadAsStreamAsync(ct);
        return (body, fileName);
    }

    // ─── Служебное ─────────────────────────────────────────────────────

    public async Task<HealthResponse?> HealthAsync(CancellationToken ct)
    {
        try
        {
            return await _http.GetFromJsonAsync<HealthResponse>("/health", JsonOptions, ct);
        }
        catch (Exception ex)
        {
            _log.LogWarning(ex, "Generator service health probe failed");
            return null;
        }
    }
}
