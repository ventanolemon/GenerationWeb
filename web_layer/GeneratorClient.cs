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
    public async Task<(JsonElement? Body, string? Error, int Status)> GenerateAsync(
        GenerateRequest request, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/generate",
            new
            {
                partition_id = request.PartitionId,
                user_id = request.UserId,
                interactive = request.Interactive,
                session_mode = request.SessionMode,
                max_attempts = request.MaxAttempts
            },
            ct);

        // 404 разбирается первым и означает не ошибку запроса, а «нет
        // генератора для этого раздела» — у эндпоинта своя формулировка.
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return (null, null, 0);
        }

        // Любой 4xx пересылается как есть, с сохранением кода. Причин две
        // и они разные: 400 — режим прохождения, который описан, но ещё не
        // открыт (ДЗ, зачёт); 422 — не прошедшая валидацию max_attempts.
        // Ловить только 400 значило бы отправить 422 в
        // EnsureSuccessStatusCode и показать пользователю голую 500 вместо
        // объяснения, которое сервис уже написал словами.
        if ((int)response.StatusCode >= 400 && (int)response.StatusCode < 500)
        {
            return (null, await response.Content.ReadAsStringAsync(ct),
                    (int)response.StatusCode);
        }

        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<JsonElement>(JsonOptions, ct),
                null, 0);
    }

    // ─── Интерактив ────────────────────────────────────────────────────

    public async Task<(TurnResultResponse? Result, bool SessionExists)> SubmitAsync(
        SubmitRequest request, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/interactive/submit",
            new
            {
                session_id = request.SessionId,
                user_input = request.UserInput ?? string.Empty,
                tolerant = request.Tolerant,
                // null, а не пустой словарь: у FastAPI это различимо —
                // отсутствие поля значит «отвечали строкой», и пустой
                // словарь вместо него означал бы пустой ответ по всем полям.
                values = request.Values
            },
            ct);

        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return (null, false);
        }

        response.EnsureSuccessStatusCode();
        var result = await response.Content.ReadFromJsonAsync<TurnResultResponse>(JsonOptions, ct);
        return (result, true);
    }

    // ─── Предпросмотр «что примут» (материал преподавателя) ────────────

    /// <summary>
    /// Список ответов, которые будут засчитаны данной спецификацией.
    ///
    /// Отдаём сырым JsonElement по той же причине, что и задание:
    /// структура принадлежит ядру, и типизировать её здесь значило бы
    /// править веб-слой при каждом новом виде ответа.
    ///
    /// Возвращает текст ошибки при 400 — спецификацию сюда приносит
    /// редактор, и «не разобралась» это нормальный ответ на недописанное
    /// объявление, а не сбой.
    /// </summary>
    public async Task<(JsonElement? Body, string? Error, int Status)> PreviewAnswerAsync(
        JsonElement spec, string? mode, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/answers/preview", new { spec, mode }, ct);

        if ((int)response.StatusCode >= 400 && (int)response.StatusCode < 500)
        {
            return (null, await response.Content.ReadAsStringAsync(ct),
                    (int)response.StatusCode);
        }

        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<JsonElement>(JsonOptions, ct),
                null, 0);
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

    // ─── Авторизация и профиль ──────────────────────────────────────────────

    public async Task<UserDto?> LoginAsync(string login, string password, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/auth/login",
            new { login, password },
            ct);
        if (response.StatusCode == System.Net.HttpStatusCode.Unauthorized)
            return null;
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<UserDto>(JsonOptions, ct);
    }

    public async Task<(UserDto? User, string? Error)> RegisterAsync(
        RegisterRequest req, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/auth/register",
            new { login = req.Login, password = req.Password,
                  fio = req.Fio, group = req.Group, email = req.Email },
            ct);
        if (response.StatusCode == System.Net.HttpStatusCode.Conflict)
        {
            var detail = await TryReadDetail(response, ct);
            return (null, detail ?? "Логин уже занят");
        }
        response.EnsureSuccessStatusCode();
        var user = await response.Content.ReadFromJsonAsync<UserDto>(JsonOptions, ct);
        return (user, null);
    }

    public async Task<UserDto?> GetProfileAsync(string login, CancellationToken ct)
    {
        var response = await _http.GetAsync(
            $"/auth/profile/{Uri.EscapeDataString(login)}", ct);
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound) return null;
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<UserDto>(JsonOptions, ct);
    }

    public async Task<UserDto?> UpdateProfileAsync(
        string login, UpdateProfileRequest req, CancellationToken ct)
    {
        var response = await _http.PatchAsJsonAsync(
            $"/auth/profile/{Uri.EscapeDataString(login)}",
            new { fio = req.Fio, group = req.Group, email = req.Email,
                  about = req.About, avatar_color = req.AvatarColor },
            ct);
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound) return null;
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<UserDto>(JsonOptions, ct);
    }

    public async Task<(bool Ok, string? Error)> ChangePasswordAsync(
        ChangePasswordRequest req, CancellationToken ct)
    {
        var response = await _http.PostAsJsonAsync(
            "/auth/change-password",
            new { login = req.Login,
                  current_password = req.CurrentPassword,
                  new_password = req.NewPassword },
            ct);
        if (response.StatusCode == System.Net.HttpStatusCode.Unauthorized)
        {
            var detail = await TryReadDetail(response, ct);
            return (false, detail ?? "Неверный текущий пароль");
        }
        response.EnsureSuccessStatusCode();
        return (true, null);
    }

    private static async Task<string?> TryReadDetail(
        HttpResponseMessage response, CancellationToken ct)
    {
        try
        {
            var json = await response.Content
                .ReadFromJsonAsync<System.Text.Json.JsonElement>(cancellationToken: ct);
            if (json.TryGetProperty("detail", out var d)) return d.GetString();
        }
        catch { }
        return null;
    }

    // ─── Статистика ──────────────────────────────────────────────────────────

    /// <summary>
    /// Статистика словарного тренажёра. userId == null → гостевая статистика.
    /// Возвращаем сырой JsonElement (summary + words[]) для фронта.
    /// </summary>
    public async Task<JsonElement?> GetStatsAsync(string? userId, CancellationToken ct)
    {
        var url = string.IsNullOrEmpty(userId)
            ? "/stats"
            : $"/stats?user_id={Uri.EscapeDataString(userId)}";
        var response = await _http.GetAsync(url, ct);
        if (response.StatusCode == System.Net.HttpStatusCode.ServiceUnavailable)
            return null;
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<JsonElement>(JsonOptions, ct);
    }

    // ─── Управление разделами ────────────────────────────────────────────

    // Типизированных методов разделов здесь больше нет — ни мутаций, ни
    // чтения. Все четыре требуют identity и внятного релея отказа, а старые
    // звали EnsureSuccessStatusCode, превращая честный 403 в необработанное
    // исключение, то есть в 500 на фронт. Теперь их путь — общий ProxyAsync
    // ниже, как у остальных RBAC-вызовов.

    // ─── RBAC-прокси (/analytics, /admin, /assignments, /groups) ──────────

    /// <summary>
    /// Тонкий прокси к FastAPI-эндпоинтам, требующим identity. Пробрасывает
    /// X-User-Id / X-User-Role и возвращает статус + сырое тело как есть —
    /// маппинг формы делает фронт (как со /stats). Тело ошибок FastAPI
    /// ({"detail": ...}) переводит в контракт web-слоя ({"error": ...}) на
    /// уровне эндпоинта.
    ///
    /// Полагается на HttpClientFactory-пул: новый HttpRequestMessage на вызов
    /// корректно живёт в рамках типизированного клиента.
    /// </summary>
    public async Task<(int Status, string Body)> ProxyAsync(
        HttpMethod method, string path, string? userId, string? role,
        string? jsonBody, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(method, path);
        if (!string.IsNullOrWhiteSpace(userId))
            req.Headers.TryAddWithoutValidation("X-User-Id", userId);
        if (!string.IsNullOrWhiteSpace(role))
            req.Headers.TryAddWithoutValidation("X-User-Role", role);
        if (jsonBody is not null)
            req.Content = new StringContent(
                jsonBody, System.Text.Encoding.UTF8, "application/json");

        using var resp = await _http.SendAsync(req, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        return ((int)resp.StatusCode, body);
    }

    /// <summary>
    /// Релей публичного API (/api/v1/* → /v1/*). Отличается от ProxyAsync
    /// субъектом и конвертом: пробрасывает Authorization и Origin вместо
    /// X-User-Id/X-User-Role, а тело ответа отдаёт нетронутым — у /v1 свой
    /// контракт ошибки, и переписывать его по дороге нельзя.
    ///
    /// X-Request-Id ходит в ОБЕ стороны, и обратная важнее прямой. Свой
    /// идентификатор интегратор и так знает; а когда он его не прислал,
    /// сервис генерирует свой — и без возврата в ответе тот остаётся
    /// только в наших логах. Тогда обещание «по X-Request-Id вызов
    /// соотносится с записями в логе» превращается в «напишите нам время и
    /// примерный запрос», то есть ни во что.
    /// </summary>
    public async Task<(int Status, string Body, string? RequestId)>
        ForwardPublicAsync(
            HttpMethod method, string path, string? authorization,
            string? origin, string? requestId, string? jsonBody,
            CancellationToken ct)
    {
        using var req = new HttpRequestMessage(method, path);
        if (!string.IsNullOrWhiteSpace(authorization))
            req.Headers.TryAddWithoutValidation("Authorization", authorization);
        if (!string.IsNullOrWhiteSpace(origin))
            req.Headers.TryAddWithoutValidation("Origin", origin);
        if (!string.IsNullOrWhiteSpace(requestId))
            req.Headers.TryAddWithoutValidation("X-Request-Id", requestId);
        if (jsonBody is not null)
            req.Content = new StringContent(
                jsonBody, System.Text.Encoding.UTF8, "application/json");

        using var resp = await _http.SendAsync(req, ct);
        var body = await resp.Content.ReadAsStringAsync(ct);
        var upstreamId = resp.Headers.TryGetValues("X-Request-Id", out var ids)
            ? ids.FirstOrDefault()
            : null;
        return ((int)resp.StatusCode, body, upstreamId ?? requestId);
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
