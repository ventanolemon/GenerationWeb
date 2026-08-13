using System.Text.Json;
using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// POST /api/answers/preview — «что примут» для преподавателя.
///
/// Единственный маршрут в веб-слое, который обслуживает не проходящего
/// задание, а того, кто его настраивает. Без списка «эти ответы будут
/// засчитаны» рядом с переключателем строгости автопроверку выключают на
/// второй день, потому что не доверяют ей.
///
/// Своего состояния нет: спецификация приходит в теле и уезжает в FastAPI,
/// где живёт единственная реализация проверки. Считать примеры здесь
/// значило бы завести вторую, которая разойдётся с первой.
/// </summary>
public static class AnswersEndpoints
{
    public static void MapAnswersEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/answers/preview", async (
            AnswerPreviewRequest body,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            if (body.Spec.ValueKind != JsonValueKind.Object)
            {
                return Results.BadRequest(new
                {
                    error = "spec must be an object"
                });
            }

            var (result, error, status) = await client.PreviewAnswerAsync(
                body.Spec, body.Mode, ct);

            if (error is not null)
            {
                // Спецификацию приносит редактор, и «не разобралась» —
                // нормальный ответ на недописанное объявление. Причину и
                // код формулирует ядро, мы их не переписываем.
                return Results.Content(error, "application/json",
                                       statusCode: status);
            }

            return Results.Ok(result);
        })
        .WithTags("answers");
    }
}
