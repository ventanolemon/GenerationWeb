using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// База знаний: чтение страниц с наложенными правками и правка страниц.
///
/// Появилось потому, что без этого база знаний РАЗВОРАЧИВАЛАСЬ ТОЛЬКО В
/// РЕЖИМЕ РАЗРАБОТКИ. Правки ходят на /api/guide, а в dev-режиме этот
/// префикс переадресует Vite прямо на FastAPI. В настоящем развёртывании
/// Vite нет: запрос приходил бы сюда и получал 404, то есть кнопка
/// «Править» была бы видна и не работала.
///
/// Слой тонкий, как и везде здесь: пробрасывает identity и релеит тело.
/// Кто имеет право править (администратор и разработчик), решает
/// generator_service — 403 приходит оттуда и с готовым текстом.
///
/// Чтение открыто ВСЕМ, включая гостя, и это не упущение: база знаний
/// открыта гостю намеренно. Закрой мы чтение — гость видел бы
/// поставочную страницу, а вошедший исправленную, и расходились бы они
/// молча.
/// </summary>
public static class GuideEndpoints
{
    public static void MapGuideEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/guide", async (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
        {
            var (uid, role, auth) = ProxyRelay.Identity(req);
            var (status, body) = await c.ProxyAsync(HttpMethod.Get, "/guide", uid, role, null, ct, auth);
            return ProxyRelay.Relay(status, body);
        }).WithTags("guide");

        app.MapPut("/api/guide/{pageId}", async (string pageId, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
        {
            var (uid, role, auth) = ProxyRelay.Identity(req);
            var json = await ProxyRelay.ReadBodyAsync(req);
            var (status, body) = await c.ProxyAsync(
                HttpMethod.Put, $"/guide/{Uri.EscapeDataString(pageId)}", uid, role, json, ct, auth);
            return ProxyRelay.Relay(status, body);
        }).WithTags("guide");

        app.MapDelete("/api/guide/{pageId}", async (string pageId, HttpRequest req, GeneratorClient c, CancellationToken ct) =>
        {
            var (uid, role, auth) = ProxyRelay.Identity(req);
            var (status, body) = await c.ProxyAsync(
                HttpMethod.Delete, $"/guide/{Uri.EscapeDataString(pageId)}", uid, role, null, ct, auth);
            return ProxyRelay.Relay(status, body);
        }).WithTags("guide");
    }
}
