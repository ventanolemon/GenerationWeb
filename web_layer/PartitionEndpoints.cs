using System.Text.Json;
using Microsoft.Extensions.Caching.Memory;
using WebLayer.Contracts;
using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// CRUD разделов — создание, редактирование, удаление.
///
/// После каждой мутации инвалидируем кеш разделов в IMemoryCache,
/// чтобы следующий GET /api/subjects/{id}/partitions вернул актуальные данные.
///
/// FastAPI перестраивает registry автоматически при каждой мутации.
///
/// ## Мутации пробрасывают identity
///
/// `POST` и `DELETE` идут через ProxyAsync с X-User-Id / X-User-Role — как
/// аналитика и администрирование, и по той же причине: авторизацию делает
/// generator_service (401 без identity, 403 при чужом предмете), а он не
/// может её сделать, не зная, кто пришёл. Раньше заголовки не
/// пробрасывались вовсе, и сервису оставалось верить любому запросу на
/// слово.
///
/// Заодно ответ теперь релеится, а не проглатывается: `EnsureSuccessStatusCode`
/// превращал честный 403 в необработанное исключение, то есть в 500 —
/// пользователь видел «сервис упал» вместо «нельзя».
///
/// Чтение (`GET`) — тоже с identity, и по той же причине: сервис
/// авторизует его скоупом выдач (401 без identity, 403 студенту, 404 на
/// чужой предмет), а без заголовков решить это не может. Речь именно про
/// эти два эндпоинта: они отдают устройство раздела и список кандидатов,
/// то есть работу редактора. Витрину (`GET /api/subjects/...`) это не
/// касается — она отдаёт имена, и по ней ходит решающий задачи гость.
/// </summary>
public static class PartitionEndpoints
{
    public static void MapPartitionEndpoints(this IEndpointRouteBuilder app)
    {
        // GET /api/partitions/candidates/{subjectId}
        app.MapGet("/api/partitions/candidates/{subjectId:int}", async (
            int subjectId,
            HttpRequest req,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var (uid, role, auth) = ProxyRelay.Identity(req);
            var (status, body) = await client.ProxyAsync(
                HttpMethod.Get, $"/partitions/candidates/{subjectId}",
                uid, role, null, ct, auth);
            return ProxyRelay.Relay(status, body);
        })
        .WithTags("partitions");

        // GET /api/partitions/{id}
        app.MapGet("/api/partitions/{id:int}", async (
            int id,
            HttpRequest req,
            GeneratorClient client,
            CancellationToken ct) =>
        {
            var (uid, role, auth) = ProxyRelay.Identity(req);
            var (status, body) = await client.ProxyAsync(
                HttpMethod.Get, $"/partitions/{id}", uid, role, null, ct, auth);
            return ProxyRelay.Relay(status, body);
        })
        .WithTags("partitions");

        // POST /api/partitions — upsert
        app.MapPost("/api/partitions", async (
            UpsertPartitionRequest body,
            HttpRequest req,
            GeneratorClient client,
            IMemoryCache cache,
            CancellationToken ct) =>
        {
            if (string.IsNullOrWhiteSpace(body.Name))
                return Results.BadRequest(new { error = "name is required" });

            // Тело пересобираем из DTO, а не читаем сырым: связывание уже
            // забрало поток, да и SubjectId нужен для инвалидации кеша.
            var payload = JsonSerializer.Serialize(new
            {
                subject_id = body.SubjectId,
                name = body.Name,
                constracted = body.Constracted,
                generation_params = body.GenerationParams ?? (object)new { },
            });

            var (uid, role, auth) = ProxyRelay.Identity(req);
            var (status, respBody) = await client.ProxyAsync(
                HttpMethod.Post, "/partitions", uid, role, payload, ct, auth);

            // Кеш сбрасываем ТОЛЬКО после успеха: на 403 ничего не менялось,
            // а лишний сброс заставил бы всех перечитывать разделы из-за
            // чужой неудачной попытки.
            if (status is >= 200 and < 300)
                cache.Remove($"partitions:{body.SubjectId}");
            return ProxyRelay.Relay(status, respBody);
        })
        .WithTags("partitions");

        // DELETE /api/partitions/{id}
        app.MapDelete("/api/partitions/{id:int}", async (
            int id,
            int subjectId,
            HttpRequest req,
            GeneratorClient client,
            IMemoryCache cache,
            CancellationToken ct) =>
        {
            var (uid, role, auth) = ProxyRelay.Identity(req);
            var (status, respBody) = await client.ProxyAsync(
                HttpMethod.Delete, $"/partitions/{id}", uid, role, null, ct, auth);

            // Инвалидируем кеш предмета — subjectId передаётся query-параметром
            if (status is >= 200 and < 300)
                cache.Remove($"partitions:{subjectId}");
            return ProxyRelay.Relay(status, respBody);
        })
        .WithTags("partitions");
    }
}
