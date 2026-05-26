using Microsoft.Extensions.Caching.Memory;
using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// CRUD разделов — создание, редактирование, удаление.
///
/// После каждой мутации инвалидируем кеш разделов в IMemoryCache,
/// чтобы следующий GET /api/subjects/{id}/partitions вернул актуальные данные.
///
/// FastAPI перестраивает registry автоматически при каждой мутации.
/// </summary>
public static class PartitionEndpoints
{
    public static void MapPartitionEndpoints(this IEndpointRouteBuilder app)
    {
        // GET /api/partitions/candidates/{subjectId}
        app.MapGet("/api/partitions/candidates/{subjectId:int}", async (
            int subjectId,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var result = await client.GetPartitionCandidatesAsync(subjectId, ct);
            return result is null
                ? Results.NotFound(new { error = $"Subject {subjectId} not found" })
                : Results.Ok(result);
        })
        .WithTags("partitions");

        // GET /api/partitions/{id}
        app.MapGet("/api/partitions/{id:int}", async (
            int id,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var part = await client.GetPartitionForEditAsync(id, ct);
            return part is null
                ? Results.NotFound(new { error = $"Partition {id} not found" })
                : Results.Ok(part);
        })
        .WithTags("partitions");

        // POST /api/partitions — upsert
        app.MapPost("/api/partitions", async (
            UpsertPartitionRequest body,
            GeneratorClient client,
            IMemoryCache cache,
            CancellationToken ct) =>
        {
            if (string.IsNullOrWhiteSpace(body.Name))
                return Results.BadRequest(new { error = "name is required" });

            var pid = await client.UpsertPartitionAsync(
                body.SubjectId, body.Name, body.Constracted,
                body.GenerationParams, ct);

            if (pid is null)
                return Results.Problem("Failed to upsert partition");

            cache.Remove($"partitions:{body.SubjectId}");
            return Results.Ok(new { partition_id = pid });
        })
        .WithTags("partitions");

        // DELETE /api/partitions/{id}
        app.MapDelete("/api/partitions/{id:int}", async (
            int id,
            int subjectId,
            GeneratorClient client,
            IMemoryCache cache,
            CancellationToken ct) =>
        {
            var ok = await client.DeletePartitionAsync(id, ct);
            if (!ok)
                return Results.NotFound(new { error = $"Partition {id} not found" });

            // Инвалидируем кеш всех предметов — subjectId передаётся query-параметром
            cache.Remove($"partitions:{subjectId}");
            return Results.Ok(new { deleted = id });
        })
        .WithTags("partitions");
    }
}
