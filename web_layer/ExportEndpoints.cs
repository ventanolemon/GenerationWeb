using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// POST /api/export — скачать .docx с заданиями.
///
/// Мы не материализуем файл в памяти, а сразу прокидываем поток из
/// FastAPI клиенту через Results.File. Это важно для больших экспортов:
/// при count=20 и наличии формул .docx может весить несколько мегабайт,
/// держать его в byte[] на каждом запросе расточительно.
///
/// Поток закрывает Kestrel сам после отправки ответа.
/// </summary>
public static class ExportEndpoints
{
    public const string DocxMime =
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

    public static void MapExportEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/api/export", async (
            ExportRequest body,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            if (body.PartitionId <= 0)
            {
                return Results.BadRequest(new { error = "partition_id must be positive" });
            }
            if (body.Count is < 1 or > 50)
            {
                return Results.BadRequest(new { error = "count must be between 1 and 50" });
            }

            try
            {
                var (stream, fileName) = await client.ExportAsync(body, ct);
                if (stream is null)
                {
                    return Results.NotFound(new
                    {
                        error = $"No generator for partition {body.PartitionId}"
                    });
                }

                return Results.File(
                    fileStream: stream,
                    contentType: DocxMime,
                    fileDownloadName: fileName ?? $"tasks_{body.PartitionId}.docx");
            }
            catch (HttpRequestException ex)
                when (ex.StatusCode == System.Net.HttpStatusCode.BadRequest)
            {
                // Например, попытка экспорта интерактивного раздела —
                // FastAPI отвечает 400, и мы прокидываем это фронту как 400.
                return Results.BadRequest(new
                {
                    error = "Export is not available for this partition (likely interactive)"
                });
            }
        })
        .WithTags("export");
    }
}
