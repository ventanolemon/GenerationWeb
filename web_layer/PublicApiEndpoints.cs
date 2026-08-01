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
///     контракт, и переписывать его по дороге значило бы его сломать.
/// </summary>
public static class PublicApiEndpoints
{
    private const string UpstreamPrefix = "/v1";

    public static void MapPublicApiEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/v1/me", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Forward(HttpMethod.Get, "/me", req, c, ct))
           .WithTags("public-v1");

        app.MapGet("/api/v1/catalog", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Forward(HttpMethod.Get, "/catalog", req, c, ct))
           .WithTags("public-v1");

        app.MapPost("/api/v1/tasks", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Forward(HttpMethod.Post, "/tasks", req, c, ct))
           .WithTags("public-v1");

        app.MapPost("/api/v1/tasks/{sessionId}/answer",
            (string sessionId, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
                Forward(HttpMethod.Post, $"/tasks/{Uri.EscapeDataString(sessionId)}/answer",
                        req, c, ct))
           .WithTags("public-v1");
    }

    private static async Task<IResult> Forward(
        HttpMethod method, string path, HttpRequest req,
        GeneratorClient client, CancellationToken ct)
    {
        var body = await ProxyRelay.ReadBodyAsync(req);
        var (status, payload) = await client.ForwardPublicAsync(
            method,
            UpstreamPrefix + path,
            req.Headers.Authorization.FirstOrDefault(),
            req.Headers.Origin.FirstOrDefault(),
            req.Headers["X-Request-Id"].FirstOrDefault(),
            body,
            ct);

        // Тело — как есть, в обе стороны: и успех, и ошибка уже в контракте
        // публичного API.
        return Results.Content(payload, "application/json", statusCode: status);
    }
}
