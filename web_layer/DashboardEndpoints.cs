using System.Text.Json;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Прокси к RBAC-эндпоинтам FastAPI: аналитика, администрирование, группы,
/// домашки. Web-слой здесь намеренно тонкий — он лишь пробрасывает identity
/// (X-User-Id / X-User-Role из браузера) и релеит сырое тело. Вся логика и
/// авторизация — в generator_service (401 без identity, 403 при недостатке
/// роли, 400 на доменных ошибках).
///
/// Форму ответов знает только фронт (как со /stats): C#-слою незачем
/// типизировать overview/users/assignments. Ошибки FastAPI ({"detail": ...})
/// переводятся в контракт web-слоя ({"error": ...}).
/// </summary>
public static class DashboardEndpoints
{
    public static void MapDashboardEndpoints(this IEndpointRouteBuilder app)
    {
        // ─── Аналитика ───────────────────────────────────────────────────
        app.MapGet("/api/analytics/overview", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/analytics/overview" + req.QueryString.Value, req, ct))
            .WithTags("analytics");

        // ─── Администрирование: пользователи ─────────────────────────────
        app.MapGet("/api/admin/users", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/admin/users", req, ct))
            .WithTags("admin");

        app.MapPost("/api/admin/users/{login}/role", (string login, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, $"/admin/users/{Uri.EscapeDataString(login)}/role", req, ct))
            .WithTags("admin");

        // ─── Администрирование: группы ───────────────────────────────────
        app.MapGet("/api/admin/groups", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/admin/groups", req, ct))
            .WithTags("admin");

        app.MapPost("/api/admin/groups", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, "/admin/groups", req, ct))
            .WithTags("admin");

        app.MapPost("/api/admin/groups/{gid:int}/members", (int gid, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, $"/admin/groups/{gid}/members", req, ct))
            .WithTags("admin");

        app.MapDelete("/api/admin/groups/{gid:int}/members/{login}", (int gid, string login, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Delete, c, $"/admin/groups/{gid}/members/{Uri.EscapeDataString(login)}", req, ct))
            .WithTags("admin");

        app.MapPost("/api/admin/groups/{gid:int}/teachers", (int gid, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, $"/admin/groups/{gid}/teachers", req, ct))
            .WithTags("admin");

        app.MapDelete("/api/admin/groups/{gid:int}/teachers/{login}", (int gid, string login, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Delete, c, $"/admin/groups/{gid}/teachers/{Uri.EscapeDataString(login)}", req, ct))
            .WithTags("admin");

        // ─── Группы преподавателя ────────────────────────────────────────
        app.MapGet("/api/groups/mine", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/groups/mine", req, ct))
            .WithTags("groups");

        // ─── Домашки ─────────────────────────────────────────────────────
        app.MapPost("/api/assignments", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, "/assignments", req, ct))
            .WithTags("assignments");

        app.MapGet("/api/assignments/teaching", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/assignments/teaching", req, ct))
            .WithTags("assignments");

        app.MapGet("/api/assignments/mine", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/assignments/mine", req, ct))
            .WithTags("assignments");

        app.MapGet("/api/assignments/{id:int}/progress", (int id, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, $"/assignments/{id}/progress", req, ct))
            .WithTags("assignments");

        app.MapDelete("/api/assignments/{id:int}", (int id, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Delete, c, $"/assignments/{id}", req, ct))
            .WithTags("assignments");
    }

    // ─── Вспомогательное ─────────────────────────────────────────────────

    private static async Task<IResult> Get(
        GeneratorClient client, string path, HttpRequest req, CancellationToken ct)
    {
        var (uid, role) = Identity(req);
        var (status, body) = await client.ProxyAsync(HttpMethod.Get, path, uid, role, null, ct);
        return Relay(status, body);
    }

    private static async Task<IResult> Send(
        HttpMethod method, GeneratorClient client, string path, HttpRequest req, CancellationToken ct)
    {
        var (uid, role) = Identity(req);
        var jsonBody = await ReadBodyAsync(req);
        var (status, body) = await client.ProxyAsync(method, path, uid, role, jsonBody, ct);
        return Relay(status, body);
    }

    private static (string? uid, string? role) Identity(HttpRequest req) =>
        (req.Headers["X-User-Id"].FirstOrDefault(), req.Headers["X-User-Role"].FirstOrDefault());

    private static async Task<string?> ReadBodyAsync(HttpRequest req)
    {
        if (req.ContentLength is 0) return null;
        using var reader = new StreamReader(req.Body);
        var s = await reader.ReadToEndAsync();
        return string.IsNullOrWhiteSpace(s) ? null : s;
    }

    /// <summary>
    /// 2xx — тело как есть. Иначе {"detail": ...} FastAPI → {"error": ...}
    /// web-слоя (тот же контракт, что читает фронтовый ApiError).
    /// </summary>
    private static IResult Relay(int status, string body)
    {
        if (status is >= 200 and < 300)
            return Results.Content(body, "application/json", statusCode: status);

        var error = "Ошибка сервиса";
        try
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("detail", out var d))
                error = d.ValueKind == JsonValueKind.String ? d.GetString() ?? error : d.ToString();
        }
        catch
        {
            // тело не JSON — оставляем общий текст
        }
        return Results.Json(new { error }, statusCode: status);
    }
}
