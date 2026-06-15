using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// POST /api/generate — попросить генератор-сервис создать задание.
///
/// FastAPI отвечает либо StaticTask (с полями statement/answer/meta),
/// либо InteractiveStart (с session_id и prompt). Здесь мы прокидываем
/// сырой JsonElement дальше — фронт по полю "type" решает, что рендерить.
///
/// Никакого кеширования здесь нет — каждая генерация по определению
/// должна давать новое задание.
/// </summary>
public static class GenerateEndpoints
{
    public static void MapGenerateEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/generate", async (
            GenerateRequest body,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            if (body.PartitionId <= 0)
            {
                return Results.BadRequest(new { error = "partition_id must be positive" });
            }

            var result = await client.GenerateAsync(body.PartitionId, body.UserId, ct);
            if (result is null)
            {
                return Results.NotFound(new
                {
                    error = $"No generator for partition {body.PartitionId}"
                });
            }

            return Results.Ok(result);
        })
        .WithTags("generate");
    }
}
