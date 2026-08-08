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

        // ─── Организации (§8) ────────────────────────────────────────────
        // Кто что может, решает FastAPI: заводить организации и раздавать
        // флаг администратора развёртывания — только is_superuser, принимать
        // и исключать людей — админ своей организации. Здесь, как и везде в
        // web_layer, проверок роли нет — только релей.
        app.MapGet("/api/organizations/mine", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/organizations/mine", req, ct))
            .WithTags("organizations");

        app.MapGet("/api/admin/organizations", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/admin/organizations", req, ct))
            .WithTags("organizations");

        app.MapPost("/api/admin/organizations", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, "/admin/organizations", req, ct))
            .WithTags("organizations");

        app.MapGet("/api/admin/organizations/{oid:int}", (int oid, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, $"/admin/organizations/{oid}", req, ct))
            .WithTags("organizations");

        app.MapPatch("/api/admin/organizations/{oid:int}", (int oid, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Patch, c, $"/admin/organizations/{oid}", req, ct))
            .WithTags("organizations");

        app.MapPost("/api/admin/organizations/{oid:int}/members", (int oid, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, $"/admin/organizations/{oid}/members", req, ct))
            .WithTags("organizations");

        app.MapDelete("/api/admin/organizations/{oid:int}/members/{login}", (int oid, string login, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Delete, c, $"/admin/organizations/{oid}/members/{Uri.EscapeDataString(login)}", req, ct))
            .WithTags("organizations");

        app.MapPost("/api/admin/organizations/{oid:int}/owner", (int oid, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, $"/admin/organizations/{oid}/owner", req, ct))
            .WithTags("organizations");

        app.MapPost("/api/admin/superusers/{login}", (string login, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, $"/admin/superusers/{Uri.EscapeDataString(login)}", req, ct))
            .WithTags("organizations");

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
        var (uid, role, auth) = ProxyRelay.Identity(req);
        var (status, body) = await client.ProxyAsync(HttpMethod.Get, path, uid, role, null, ct, auth);
        return ProxyRelay.Relay(status, body);
    }

    private static async Task<IResult> Send(
        HttpMethod method, GeneratorClient client, string path, HttpRequest req, CancellationToken ct)
    {
        var (uid, role, auth) = ProxyRelay.Identity(req);
        var jsonBody = await ProxyRelay.ReadBodyAsync(req);
        var (status, body) = await client.ProxyAsync(method, path, uid, role, jsonBody, ct, auth);
        return ProxyRelay.Relay(status, body);
    }
}
