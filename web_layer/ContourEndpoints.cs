using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Прокси к LLM-контуру (contour_service, отдельный микросервис). Web-слой
/// тонкий: пробрасывает identity (X-User-Id / X-User-Role) и релеит сырое
/// тело. Вся логика — очередь, петля S0–S6, владение джобами, создание
/// партиции из approve — в contour_service; RBAC (кто вообще ходит) — здесь.
///
/// Форму job/probe/critic знает только фронт (как со /stats и dashboard-
/// прокси). Ошибки contour_service ({"detail": ...}) переводятся в контракт
/// web-слоя ({"error": ...}) через ProxyRelay.
/// </summary>
public static class ContourEndpoints
{
    public static void MapContourEndpoints(this IEndpointRouteBuilder app)
    {
        // Создать джобу (teacher/admin — гейтит contour_service).
        app.MapPost("/api/contour/jobs", (HttpRequest req, ContourClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, "/contour/jobs", req, ct))
            .WithTags("contour");

        // Список джоб пользователя (admin — все).
        app.MapGet("/api/contour/jobs", (HttpRequest req, ContourClient c, CancellationToken ct) =>
            Get(c, "/contour/jobs", req, ct))
            .WithTags("contour");

        // Деталь джобы: статус, превью, probe-отчёт, вердикт критика, раунды.
        app.MapGet("/api/contour/jobs/{jobId}", (string jobId, HttpRequest req, ContourClient c, CancellationToken ct) =>
            Get(c, $"/contour/jobs/{Uri.EscapeDataString(jobId)}", req, ct))
            .WithTags("contour");

        // S6: принять → партиция constracted=4 + корпусная запись.
        app.MapPost("/api/contour/jobs/{jobId}/approve", (string jobId, HttpRequest req, ContourClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, $"/contour/jobs/{Uri.EscapeDataString(jobId)}/approve", req, ct))
            .WithTags("contour");

        // S6: отклонить (причина в лог эскалаций).
        app.MapPost("/api/contour/jobs/{jobId}/reject", (string jobId, HttpRequest req, ContourClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, $"/contour/jobs/{Uri.EscapeDataString(jobId)}/reject", req, ct))
            .WithTags("contour");
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
