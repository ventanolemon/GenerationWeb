using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Редактор графов: каталог узлов, поставочные файлы, проверка и
/// предпросмотр.
///
/// Почему этого не было раньше и почему появилось
/// ----------------------------------------------
/// Контракт (`docs/architecture/graph_editor_api_contract.md` §2) отправлял
/// `/api/graph` прямо в generator_service мимо этого слоя, и в разработке
/// так и происходит: Vite переадресует префикс на :8000.
///
/// Но Vite есть только в разработке. В настоящем развёртывании фронт
/// раздаётся статикой, и `/api/graph` приходит СЮДА — где до сих пор не
/// было ни одного маршрута. То есть **редактор графов разворачивался
/// только вместе с dev-сервером**, а без него палитра узлов оставалась
/// пустой.
///
/// Обход этого слоя был решением про ЛОГИКУ (graph-роутер живёт в
/// generator_service, потому что там импортирован движок графов), а не
/// про маршрутизацию. Логика и осталась там: здесь только релей.
///
/// Личность здесь не требуется ни одной операции, и пробрасывается она по
/// той же причине, что и везде, — решает upstream, а не этот слой.
/// Каталог узлов и список поставочных файлов — содержимое продукта,
/// одинаковое для всех (§8).
/// </summary>
public static class GraphEndpoints
{
    public static void MapGraphEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/graph/catalog", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/graph/catalog", req, ct))
            .WithTags("graph");

        app.MapGet("/api/graph/resources", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Get(c, "/graph/resources", req, ct))
            .WithTags("graph");

        app.MapPost("/api/graph/validate", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, "/graph/validate", req, ct))
            .WithTags("graph");

        // Предпросмотр исполняет граф, пришедший из браузера. Ограничение
        // времени и ресурсов — на стороне generator_service
        // (`core/graph/isolation.py`): бесконечный цикл в чужом графе не
        // должен останавливать службу. Здесь ограничения нет намеренно —
        // второй таймаут поверх чужого дал бы обрыв соединения вместо
        // внятного отказа.
        app.MapPost("/api/graph/preview", (HttpRequest req, GeneratorClient c, CancellationToken ct) =>
            Send(HttpMethod.Post, c, "/graph/preview", req, ct))
            .WithTags("graph");
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
