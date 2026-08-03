using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Публичная поверхность /api/v1/* — вход для сторонних приложений.
///
/// Тонкий релей в generator_service, и намеренно тонкий. Ключи проверяются
/// НЕ здесь: проверка ключа неотделима от скоупа контента (какие предметы
/// доступны приложению), а скоуп живёт в той же БД, что и каталог, — то
/// есть по ту сторону. Разнеси их, и на каждый вызов пришлось бы ходить в
/// базу дважды, из двух сервисов, ради одного решения.
///
/// Тогда зачем релей вообще: `generator_service` остаётся внутренним и
/// наружу не публикуется (system_topology.md §6.2). Наружу смотрит только
/// web_layer — он держит TLS, CORS и лимиты соединений, а инвариант
/// «клиенты не ходят мимо web_layer» продолжает выполняться и для чужих
/// приложений.
///
/// Отличия от прокси внутренних эндпоинтов (DashboardEndpoints и т.п.):
///   * пробрасывается Authorization, а не X-User-Id/X-User-Role — субъект
///     здесь приложение, а не человек;
///   * Origin передаётся как есть: браузерные ключи привязаны к нему, и
///     подменять его релею нельзя;
///   * тело ошибки НЕ переводится в {"error": "строка"} web-слоя. У /v1
///     свой конверт {error: {code, message, request_id}} — публичный
///     контракт, и переписывать его по дороге значило бы его сломать;
///   * СВОЯ политика CORS (<see cref="CorsPolicy"/>). Умолчательная —
///     список origin'ов SPA с AllowCredentials; под неё чужое приложение
///     не подходит по определению, и браузерный ключ `gw_web_…` не заработал
///     бы вовсе: браузер отбил бы запрос до того, как сервис увидел ключ.
///     Здесь разрешён любой origin и запрещены credentials — публичный API
///     ходит по Bearer, а не по cookie. Ограничение по домену никуда не
///     делось, оно просто в правильном месте: `allowed_origins` КЛЮЧА,
///     который сервис проверяет сам (core/api_clients.py). CORS браузерный
///     и обходится любым не-браузером; привязка ключа — нет.
/// </summary>
public static class PublicApiEndpoints
{
    private const string UpstreamPrefix = "/v1";

    /// <summary>Имя политики CORS публичной поверхности (см. Program.cs).</summary>
    public const string CorsPolicy = "public-v1";

    public static void MapPublicApiEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/v1/me", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Forward(HttpMethod.Get, "/me", req, c, ct))
           .WithTags("public-v1").RequireCors(CorsPolicy);

        app.MapGet("/api/v1/catalog", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Forward(HttpMethod.Get, "/catalog", req, c, ct))
           .WithTags("public-v1").RequireCors(CorsPolicy);

        app.MapPost("/api/v1/tasks", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Forward(HttpMethod.Post, "/tasks", req, c, ct))
           .WithTags("public-v1").RequireCors(CorsPolicy);

        app.MapPost("/api/v1/tasks/{sessionId}/answer",
            (string sessionId, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
                Forward(HttpMethod.Post, $"/tasks/{Uri.EscapeDataString(sessionId)}/answer",
                        req, c, ct))
           .WithTags("public-v1").RequireCors(CorsPolicy);
    }

    private static async Task<IResult> Forward(
        HttpMethod method, string path, HttpRequest req,
        GeneratorClient client, CancellationToken ct)
    {
        var body = await ProxyRelay.ReadBodyAsync(req);
        var (status, payload, requestId) = await client.ForwardPublicAsync(
            method,
            UpstreamPrefix + path,
            req.Headers.Authorization.FirstOrDefault(),
            req.Headers.Origin.FirstOrDefault(),
            req.Headers["X-Request-Id"].FirstOrDefault(),
            body,
            ct);

        // Идентификатор запроса возвращается интегратору. Когда он не
        // прислал свой, сервис сгенерировал — и без этой строки тот остался
        // бы только у нас в логах, а «сообщите X-Request-Id» превратилось бы
        // в «сообщите примерное время».
        if (!string.IsNullOrWhiteSpace(requestId))
            req.HttpContext.Response.Headers["X-Request-Id"] = requestId;

        // Тело — как есть, в обе стороны: и успех, и ошибка уже в контракте
        // публичного API.
        return Results.Content(payload, "application/json", statusCode: status);
    }
}
