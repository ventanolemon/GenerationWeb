using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Служебный эндпоинт /api/health.
///
/// Проверяет, что (1) сам Web Layer жив, (2) FastAPI отвечает.
/// Если FastAPI лежит, возвращаем 503 с подсказкой — это сразу
/// видно фронту при первом же опросе.
/// </summary>
public static class MetaEndpoints
{
    public static void MapMetaEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/health", async (
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var upstream = await client.HealthAsync(ct);
            if (upstream is null)
            {
                return Results.Json(
                    new
                    {
                        status = "degraded",
                        web = "ok",
                        generator = "unreachable"
                    },
                    statusCode: StatusCodes.Status503ServiceUnavailable);
            }

            return Results.Ok(new
            {
                status = "ok",
                web = "ok",
                generator = upstream.Status,
                generators_count = upstream.Generators
            });
        })
        .WithTags("meta");
    }
}
