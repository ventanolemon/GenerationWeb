using Microsoft.Extensions.Caching.Memory;
using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Эндпоинты справочника: предметы и их разделы.
///
/// Разделы — самый «горячий» эндпоинт, фронт дёргает его при открытии
/// страницы, поэтому здесь IMemoryCache с настраиваемым TTL.
///
/// А ВОТ ПРЕДМЕТЫ БОЛЬШЕ НЕ КЕШИРУЮТСЯ, и это не оптимизация наоборот.
/// Кеш стоял под одним ключом «subjects:all» на всё развёртывание, потому
/// что список был общим и «менялся крайне редко». После §8 он стал
/// персональным — своя организация, свои выдачи, своё личное хранилище, —
/// и общий кеш раздавал бы скоуп одного пользователя всем остальным,
/// то есть показывал бы предметы чужой организации. Плюс список перестал
/// быть неизменным: предметы теперь заводят, переименовывают и удаляют
/// прямо из интерфейса.
/// </summary>
public static class SubjectsEndpoints
{
    public static void MapSubjectsEndpoints(this IEndpointRouteBuilder app)
    {
        // Витрина и управление — оба через ProxyAsync: обоим нужна
        // identity, скоуп считает FastAPI.
        app.MapGet("/api/subjects", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Relay(HttpMethod.Get, c, "/subjects", req, ct))
           .WithTags("subjects");

        app.MapGet("/api/subjects/manage", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Relay(HttpMethod.Get, c, "/subjects/manage", req, ct))
           .WithTags("subjects");

        app.MapPost("/api/subjects", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Relay(HttpMethod.Post, c, "/subjects", req, ct))
           .WithTags("subjects");

        app.MapPatch("/api/subjects/{subjectId:int}", (int subjectId, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Relay(HttpMethod.Patch, c, $"/subjects/{subjectId}", req, ct))
           .WithTags("subjects");

        app.MapDelete("/api/subjects/{subjectId:int}", (int subjectId, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Relay(HttpMethod.Delete, c, $"/subjects/{subjectId}", req, ct))
           .WithTags("subjects");

        app.MapGet("/api/subjects/{subjectId:int}/partitions", GetPartitions)
           .WithTags("subjects");
    }

    private static async Task<IResult> Relay(
        HttpMethod method, GeneratorClient client, string path,
        HttpRequest req, CancellationToken ct)
    {
        var (uid, role, auth) = ProxyRelay.Identity(req);
        var body = method == HttpMethod.Get || method == HttpMethod.Delete
            ? null
            : await ProxyRelay.ReadBodyAsync(req);
        var (status, text) = await client.ProxyAsync(
            method, path, uid, role, body, ct, auth);
        return ProxyRelay.Relay(status, text);
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
