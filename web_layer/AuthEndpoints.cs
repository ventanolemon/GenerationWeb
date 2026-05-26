using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// POST /api/auth/login  — проверка учётных данных через FastAPI.
/// GET  /api/auth/guest  — гостевой вход (ответ без user_info).
///
/// Аутентификация клиентская: фронт хранит user_info в localStorage.
/// Сессии на сервере не создаются — это упрощённая модель, достаточная
/// для веб-версии (отображение имени, будущие word stats).
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

        app.MapGet("/api/auth/guest", () =>
            Results.Ok(new { login = (string?)null, fio = (string?)null, group = (string?)null })
        )
        .WithTags("auth");
    }
}
