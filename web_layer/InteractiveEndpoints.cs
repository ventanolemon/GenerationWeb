using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// POST /api/interactive/submit — отправка ответа в активной сессии
/// тренажёра.
///
/// Сессии хранятся в памяти FastAPI (см. session_store.py), у нас —
/// никакого состояния. Мы только пересылаем session_id и ответ
/// пользователя, отдаём результат хода как есть.
/// </summary>
public static class InteractiveEndpoints
{
    public static void MapInteractiveEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/interactive/submit", async (
            SubmitRequest body,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            if (string.IsNullOrWhiteSpace(body.SessionId))
            {
                return Results.BadRequest(new { error = "session_id is required" });
            }

            // user_input может быть пустой строкой — это легитимный кейс
            // (например, пользователь нажал Enter в пустом поле).
            var (result, exists) = await client.SubmitAsync(
                body.SessionId, body.UserInput ?? string.Empty, ct);

            if (!exists)
            {
                return Results.NotFound(new
                {
                    error = "Session not found or expired"
                });
            }

            return Results.Ok(result);
        })
        .WithTags("interactive");
    }
}
