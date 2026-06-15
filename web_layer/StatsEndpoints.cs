using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// GET /api/stats?userId=X — статистика словарного тренажёра для окна профиля.
///
/// userId — login авторизованного пользователя или гостевой UUID. Пустой/
/// отсутствующий userId означает гостевую статистику (in-memory в FastAPI).
/// Не кешируется: статистика меняется после каждого ответа в тренажёре.
/// </summary>
public static class StatsEndpoints
{
    public static void MapStatsEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/stats", async (
            string? userId,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var result = await client.GetStatsAsync(userId, ct);
            return result is null
                ? Results.Json(new { error = "Statistics unavailable" }, statusCode: 503)
                : Results.Ok(result);
        })
        .WithTags("stats");
    }
}
