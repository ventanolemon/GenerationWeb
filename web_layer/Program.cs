using Polly;
using Polly.Extensions.Http;
using WebLayer.Endpoints;
using WebLayer.Services;

var builder = WebApplication.CreateBuilder(args);

// ─── Конфигурация ───────────────────────────────────────────────────────

var generatorBaseUrl = builder.Configuration["Generator:BaseUrl"]
    ?? throw new InvalidOperationException(
        "Generator:BaseUrl is not configured. Check appsettings.json.");
var generatorTimeout = TimeSpan.FromSeconds(
    builder.Configuration.GetValue("Generator:TimeoutSeconds", 30));

// contour_service — отдельный upstream (LLM-контур, :8001). Отдельный
// BaseUrl и таймаут пощедрее: там синхронный прогон графа при approve.
var contourBaseUrl = builder.Configuration["Contour:BaseUrl"]
    ?? throw new InvalidOperationException(
        "Contour:BaseUrl is not configured. Check appsettings.json.");
var contourTimeout = TimeSpan.FromSeconds(
    builder.Configuration.GetValue("Contour:TimeoutSeconds", 60));

var corsOrigins = builder.Configuration
    .GetSection("Cors:AllowedOrigins")
    .Get<string[]>() ?? Array.Empty<string>();

// ─── Сервисы ────────────────────────────────────────────────────────────

// IMemoryCache — для справочников (subjects, partitions).
builder.Services.AddMemoryCache();

// Typed HttpClient к FastAPI. HttpClientFactory сам управляет пулом
// сокетов, повторное создание клиентов не нужно (и опасно).
//
// Polly retry policy: при 5xx или сетевом сбое повторяем до 3 раз с
// экспоненциальной задержкой. Это страхует на случай, если FastAPI
// перезапускается или в данный момент перечитывает БД.
var generatorRetry = HttpPolicyExtensions
    .HandleTransientHttpError()
    .WaitAndRetryAsync(
        retryCount: 3,
        sleepDurationProvider: attempt =>
            TimeSpan.FromMilliseconds(200 * Math.Pow(2, attempt)));

builder.Services
    .AddHttpClient<GeneratorClient>(http =>
    {
        http.BaseAddress = new Uri(generatorBaseUrl);
        http.Timeout = generatorTimeout;
    })
    // Ретраи — всем, кроме POST в публичный /v1: там квота списывается ДО
    // работы (иначе параллельные запросы проскочили бы лимит), и повтор
    // после 5xx списал бы её второй раз. Интегратор платил бы за наш сбой,
    // причём тем больнее, чем хуже нам. Тот же довод, по которому ретраев
    // нет у contour-клиента ниже.
    //
    // Contains, а не StartsWith: селектор работает уже внутри конвейера
    // обработчиков, где RequestUri разрешён относительно BaseAddress, и
    // путь зависит от того, есть ли в Generator:BaseUrl префикс. Ложное
    // срабатывание тут стоит одного невыполненного ретрая, пропуск —
    // списанной дважды квоты; внутренних путей с «/v1/» нет.
    .AddPolicyHandler(request =>
        request.Method == HttpMethod.Post
        && request.RequestUri is { } uri
        && uri.AbsolutePath.Contains("/v1/", StringComparison.Ordinal)
            ? Policy.NoOpAsync<HttpResponseMessage>()
            : generatorRetry);

// Typed HttpClient к contour_service (второй upstream). Без Polly-ретраев
// на approve: там неидемпотентная запись партиции — повтор при таймауте
// мог бы создать дубликат; читатели (GET) при желании переспросит фронт.
builder.Services
    .AddHttpClient<ContourClient>(http =>
    {
        http.BaseAddress = new Uri(contourBaseUrl);
        http.Timeout = contourTimeout;
    });

// CORS. Браузер ходит во Web Layer, дев-сервер Vite — на :5173.
// Список разрешённых origin'ов хранится в appsettings (в Development
// — расширенный).
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        if (corsOrigins.Length > 0)
        {
            policy.WithOrigins(corsOrigins)
                  .AllowAnyHeader()
                  .AllowAnyMethod()
                  .AllowCredentials();
        }
    });

    // Публичная поверхность /api/v1/* — своя политика, и без неё браузерный
    // ключ `gw_web_…` не работал бы вовсе: origin чужого приложения в
    // Cors:AllowedOrigins не попадёт никогда, и браузер отбил бы запрос до
    // того, как сервис увидел ключ.
    //
    // Любой origin и БЕЗ credentials: публичный API ходит по Bearer, а не по
    // cookie, так что подставлять чужую сессию нечему. Комбинация «любой
    // origin + credentials» вдобавок запрещена самим CORS.
    //
    // Ограничение по домену при этом не исчезает — оно там, где ему место:
    // `allowed_origins` КЛЮЧА, который проверяет сервис (core/api_clients.py).
    // CORS браузерный и обходится любым не-браузером; привязка ключа — нет.
    options.AddPolicy(PublicApiEndpoints.CorsPolicy, policy =>
        policy.AllowAnyOrigin()
              .AllowAnyHeader()
              .WithMethods("GET", "POST", "OPTIONS")
              // Иначе JS интегратора не сможет прочитать идентификатор
              // запроса даже когда мы его вернули: браузер прячет все
              // заголовки ответа, кроме перечисленных здесь.
              .WithExposedHeaders("X-Request-Id"));
});

builder.Services.AddEndpointsApiExplorer();

// ─── Сборка приложения ──────────────────────────────────────────────────

var app = builder.Build();

app.UseCors();

// ─── Регистрация эндпоинтов ────────────────────────────────────────────

app.MapAuthEndpoints();
app.MapSubjectsEndpoints();
app.MapGenerateEndpoints();
app.MapInteractiveEndpoints();
app.MapAnswersEndpoints();
app.MapExportEndpoints();
app.MapPartitionEndpoints();
app.MapStatsEndpoints();
app.MapMetaEndpoints();
app.MapDashboardEndpoints();
app.MapContourEndpoints();
app.MapCorpusEndpoints();
// Канал доставки кода на десктопы (обновления, пакеты узлов). Без
// идентичности намеренно: обновление безопасности должно доезжать и до
// того, у кого протух токен. Подлинность даёт подпись, а не эндпоинт.
app.MapUpdatesEndpoints();
// Публичная поверхность для сторонних приложений. Отдельно от остальных:
// у неё другой субъект (ключ приложения, не пользователь) и обещание
// совместимости — см. docs/architecture/public_api.md.
app.MapPublicApiEndpoints();

// Корневой эндпоинт — подсказка, что и где
app.MapGet("/", () => Results.Json(new
{
    service = "Web Layer",
    api = "/api",
    health = "/api/health"
}));

app.Logger.LogInformation(
    "Web Layer starting. Generator service: {Url}, CORS origins: [{Origins}]",
    generatorBaseUrl,
    string.Join(", ", corsOrigins));

app.Run();

// Делаем Program частично-публичным, чтобы WebApplicationFactory<Program>
// мог его поднять в интеграционных тестах. Без этой строчки тестам
// невидим точку входа в .NET 8 минимальном API.
public partial class Program { }
