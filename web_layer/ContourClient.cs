namespace WebLayer.Services;

/// <summary>
/// Типизированный клиент к FastAPI contour_service (отдельный микросервис,
/// :8001 в приватной сети — см. docs/architecture/system_topology.md §6).
/// В отличие от GeneratorClient здесь нет типизированных методов: экран
/// контура работает через сырой JSON (как /stats и dashboard-прокси), а
/// C#-слою незачем знать форму job/probe/critic. Только проброс identity и
/// релей тела.
///
/// Регистрируется отдельным Typed HttpClient с собственным BaseAddress
/// (Contour:BaseUrl) — это ВТОРОЙ upstream, не тот, что у GeneratorClient.
/// </summary>
public sealed class ContourClient
{
    private readonly HttpClient _http;

    public ContourClient(HttpClient http)
    {
        _http = http;
    }

    /// <summary>
    /// Проброс запроса к contour_service с identity-заголовками
    /// (X-User-Id / X-User-Role — contour_service доверяет только им,
    /// RBAC живёт здесь, в web_layer). Возвращает статус + сырое тело;
    /// маппинг detail→error делает вызывающий эндпоинт.
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
}
