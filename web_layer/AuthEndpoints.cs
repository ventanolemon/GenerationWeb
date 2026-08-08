using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// POST /api/auth/login   — вход, возвращает профиль И токен сессии.
/// POST /api/auth/logout  — выход, гасит сессию на сервере.
/// GET  /api/auth/guest   — гостевой вход (ответ без user_info).
///
/// Сессии теперь создаются НА СЕРВЕРЕ. Раньше здесь было написано
/// обратное — «аутентификация клиентская, фронт хранит user_info в
/// localStorage, сессии на сервере не создаются», — и это было честное
/// описание модели, писавшейся под показ имени. Беда в том, что поверх
/// неё достроили RBAC: роль ехала заголовком X-User-Role из браузера, и
/// преподавателю хватало его подменить, чтобы навсегда сделать себя
/// админом (organizations_readiness.md §4).
///
/// Теперь вход выдаёт токен, а роль сервер читает у себя в БД. Фронт
/// по-прежнему хранит профиль в localStorage — но для показа имени и
/// гейтинга витрин, а не как основание для доступа.
/// </summary>
public static class AuthEndpoints
{
    public static void MapAuthEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/auth/login", async (
            LoginRequest body,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            if (string.IsNullOrWhiteSpace(body.Login) ||
                string.IsNullOrWhiteSpace(body.Password))
            {
                return Results.BadRequest(new { error = "Введите логин и пароль" });
            }

            var user = await client.LoginAsync(body.Login, body.Password, ct);
            if (user is null)
            {
                return Results.Json(
                    new { error = "Неверный логин или пароль" },
                    statusCode: 401);
            }

            return Results.Ok(user);
        })
        .WithTags("auth");

        // Выход гасит сессию на СЕРВЕРЕ. Без этого «выйти» означало бы лишь
        // забыть токен в браузере, а выданная сессия жила бы до expires_at —
        // и оставалась годной у любого, кто успел её списать.
        app.MapPost("/api/auth/logout", async (
            HttpRequest req,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var (uid, role, auth) = ProxyRelay.Identity(req);
            var (status, body) = await client.ProxyAsync(
                HttpMethod.Post, "/auth/logout", uid, role, null, ct, auth);
            return ProxyRelay.Relay(status, body);
        })
        .WithTags("auth");

        app.MapGet("/api/auth/guest", () =>
            Results.Ok(new { login = (string?)null, fio = (string?)null, group = (string?)null })
        )
        .WithTags("auth");

        app.MapPost("/api/auth/register", async (
            RegisterRequest body,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            if (string.IsNullOrWhiteSpace(body.Login) ||
                string.IsNullOrWhiteSpace(body.Password) ||
                string.IsNullOrWhiteSpace(body.Fio))
            {
                return Results.BadRequest(new { error = "Заполните обязательные поля" });
            }

            var (user, error) = await client.RegisterAsync(body, ct);
            if (user is null)
            {
                return Results.Json(new { error }, statusCode: 409);
            }
            return Results.Created($"/api/auth/profile/{user.Login}", user);
        })
        .WithTags("auth");

        app.MapGet("/api/auth/profile/{login}", async (
            string login,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var profile = await client.GetProfileAsync(login, ct);
            return profile is null
                ? Results.NotFound(new { error = $"Пользователь {login} не найден" })
                : Results.Ok(profile);
        })
        .WithTags("auth");

        // Правка профиля идёт через ProxyAsync, а не через типизированный
        // UpdateProfileAsync: FastAPI теперь спрашивает, кто правит (свой
        // профиль или админ чужой), и ответ может быть 401/403. Типизированный
        // путь звал EnsureSuccessStatusCode и превращал законный отказ в 500,
        // а заголовки личности пронести через PatchAsJsonAsync нечем.
        app.MapPatch("/api/auth/profile/{login}", async (
            string login,
            HttpRequest req,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var (uid, role, auth) = ProxyRelay.Identity(req);
            var jsonBody = await ProxyRelay.ReadBodyAsync(req);
            var (status, body) = await client.ProxyAsync(
                HttpMethod.Patch, $"/auth/profile/{Uri.EscapeDataString(login)}",
                uid, role, jsonBody, ct, auth);
            return ProxyRelay.Relay(status, body);
        })
        .WithTags("auth");

        app.MapPost("/api/auth/change-password", async (
            ChangePasswordRequest body,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var (ok, error) = await client.ChangePasswordAsync(body, ct);
            return ok
                ? Results.Ok(new { ok = true })
                : Results.Json(new { error }, statusCode: 401);
        })
        .WithTags("auth");
    }
}
