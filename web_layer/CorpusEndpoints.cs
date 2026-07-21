using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Прокси к куратору корпуса обучающих примеров (тот же contour_service, что
/// и /contour — переиспользуем ContourClient). Тонкий проброс identity и
/// релей тела; admin-гейтинг и вся логика — в contour_service.
/// </summary>
public static class CorpusEndpoints
{
    public static void MapCorpusEndpoints(this IEndpointRouteBuilder app)
    {
        // Список записей + сводка (query: curation, kind).
        app.MapGet("/api/corpus", (HttpRequest req, ContourClient c, CancellationToken ct) =>
            Get(c, "/corpus" + req.QueryString.Value, req, ct))
            .WithTags("corpus");

        // Полная запись + курация.
        app.MapGet("/api/corpus/{recordId}", (string recordId, HttpRequest req, ContourClient c, CancellationToken ct) =>
            Get(c, $"/corpus/{Uri.EscapeDataString(recordId)}", req, ct))
            .WithTags("corpus");

        // Разметить (gold / excluded / auto) + коммент.
        app.MapPatch("/api/corpus/{recordId}/curation", (string recordId, HttpRequest req, ContourClient c, CancellationToken ct) =>
            Send(HttpMethod.Patch, c, $"/corpus/{Uri.EscapeDataString(recordId)}/curation", req, ct))
            .WithTags("corpus");
    }

    private static async Task<IResult> Get(
        ContourClient client, string path, HttpRequest req, CancellationToken ct)
    {
        var (uid, role) = ProxyRelay.Identity(req);
        var (status, body) = await client.ProxyAsync(HttpMethod.Get, path, uid, role, null, ct);
        return ProxyRelay.Relay(status, body);
    }

    private static async Task<IResult> Send(
        HttpMethod method, ContourClient client, string path, HttpRequest req, CancellationToken ct)
    {
        var (uid, role) = ProxyRelay.Identity(req);
        var jsonBody = await ProxyRelay.ReadBodyAsync(req);
        var (status, body) = await client.ProxyAsync(method, path, uid, role, jsonBody, ct);
        return ProxyRelay.Relay(status, body);
    }
}
