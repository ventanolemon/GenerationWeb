using Microsoft.Extensions.Caching.Memory;
using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Эндпоинты справочника: предметы и их разделы.
///
/// Это самые «горячие» эндпоинты — фронт дёргает их при открытии страницы.
/// Поэтому здесь IMemoryCache с настраиваемыми TTL (см. appsettings).
/// Subjects кешируем дольше (5 минут): они меняются крайне редко.
/// Partitions — короче (1 минута): пользователь может создать новую группу
/// или тест прямо из UI, и хочется, чтобы изменения подхватывались
/// быстро.
/// </summary>
public static class SubjectsEndpoints
{
    public static void MapSubjectsEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/subjects", GetSubjects)
           .WithTags("subjects");

        app.MapGet("/api/subjects/{subjectId:int}/partitions", GetPartitions)
           .WithTags("subjects");
    }

    private static async Task<IResult> GetSubjects(
        GeneratorClient client,
        IMemoryCache cache,
        IConfiguration config,
        CancellationToken ct)
    {
        const string key = "subjects:all";
        if (cache.TryGetValue(key, out List<SubjectDto>? cached) && cached is not null)
        {
            return Results.Ok(cached);
        }

        var subjects = await client.ListSubjectsAsync(ct);
        var ttl = TimeSpan.FromSeconds(config.GetValue("Cache:SubjectsSeconds", 300));
        cache.Set(key, subjects, ttl);
        return Results.Ok(subjects);
    }

    private static async Task<IResult> GetPartitions(
        int subjectId,
        GeneratorClient client,
        IMemoryCache cache,
        IConfiguration config,
        CancellationToken ct)
    {
        string key = $"partitions:{subjectId}";
        if (cache.TryGetValue(key, out List<PartitionDto>? cached) && cached is not null)
        {
            return Results.Ok(cached);
        }

        var partitions = await client.ListPartitionsAsync(subjectId, ct);
        if (partitions is null)
        {
            return Results.NotFound(new { error = $"Subject {subjectId} not found" });
        }

        var ttl = TimeSpan.FromSeconds(config.GetValue("Cache:PartitionsSeconds", 60));
        cache.Set(key, partitions, ttl);
        return Results.Ok(partitions);
    }
}
