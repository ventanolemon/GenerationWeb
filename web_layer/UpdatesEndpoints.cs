using WebLayer.Services;

namespace WebLayer.Endpoints;

/// <summary>
/// Релей канала доставки кода на десктопы: обновления приложения и пакеты
/// узлов графа.
///
///   GET /api/updates/check            что клиенту делать
///   GET /api/updates/keys             действующий набор ключей (подписанный)
///   GET /api/updates/key              отпечатки — для сверки глазами
///   GET /api/packages                 каталог пакетов узлов
///   GET /api/packages/{name}/manifest манифест и подпись для установки
///
/// ## Зачем релей
///
/// `generator_service` внутренний и наружу не публикуется
/// (`system_topology.md` §6.2), а десктоп ходит только в `web_layer` — как
/// и всё остальное. Без этих пяти строк клиентская половина обновлений
/// (репозиторий Generator, `core/updates/`) упиралась бы в никуда: код
/// проверки подписи есть, а запросить нечего.
///
/// ## Без идентичности — намеренно
///
/// Ровно по той же причине, что и на стороне сервиса: обновление
/// безопасности должно доезжать и до того, у кого протух токен или кого
/// выгнали из системы, а клиент со старым набором ключей обязан суметь
/// догнать ротацию. Скрывать факт существования версии смысла нет — она и
/// так у всех на машинах. Подлинность обеспечивает ПОДПИСЬ, проверяемая
/// клиентом по ключу, зашитому в сборку, а не закрытость эндпоинта.
///
/// ## Тело отдаётся как есть
///
/// В отличие от внутренних прокси, `{"detail": …}` НЕ переводится в
/// `{"error": …}` web-слоя: этот канал читает не SPA, а десктопный клиент,
/// который разбирает конверт сервиса и показывает пользователю его
/// сообщение. Перепиши мы тело по дороге — вместо «подпись не соответствует
/// ни одному действующему ключу» пользователь увидел бы «HTTP 400».
///
/// Артефакты (zip приложения и пакетов) сюда не ходят: в манифесте лежит
/// их прямой `url`, и качает клиент напрямую из хранилища. Раздача бинарей
/// — не задача API-слоя, а подпись делает раздатчика недоверенным звеном,
/// которому и не надо доверять.
/// </summary>
public static class UpdatesEndpoints
{
    public static void MapUpdatesEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/api/updates/check", (HttpRequest req, GeneratorClient c,
                                          CancellationToken ct) =>
            Passthrough(c, "/updates/check" + req.QueryString.Value, ct))
           .WithTags("updates");

        app.MapGet("/api/updates/keys", (GeneratorClient c,
                                         CancellationToken ct) =>
            Passthrough(c, "/updates/keys", ct))
           .WithTags("updates");

        app.MapGet("/api/updates/key", (GeneratorClient c,
                                        CancellationToken ct) =>
            Passthrough(c, "/updates/key", ct))
           .WithTags("updates");

        app.MapGet("/api/packages", (GeneratorClient c,
                                     CancellationToken ct) =>
            Passthrough(c, "/packages", ct))
           .WithTags("packages");

        app.MapGet("/api/packages/{name}/manifest",
            (string name, HttpRequest req, GeneratorClient c,
             CancellationToken ct) =>
                Passthrough(c, $"/packages/{Uri.EscapeDataString(name)}/manifest"
                               + req.QueryString.Value, ct))
           .WithTags("packages");
    }

    private static async Task<IResult> Passthrough(
        GeneratorClient client, string path, CancellationToken ct)
    {
        // Без identity: см. докстринг класса. Тело — как есть, в обе стороны.
        var (status, body) = await client.ProxyAsync(
            HttpMethod.Get, path, null, null, null, ct);
        return Results.Content(body, "application/json", statusCode: status);
    }
}
