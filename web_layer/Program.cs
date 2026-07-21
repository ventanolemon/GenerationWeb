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
builder.Services
    .AddHttpClient<GeneratorClient>(http =>
    {
        http.BaseAddress = new Uri(generatorBaseUrl);
        http.Timeout = generatorTimeout;
    })
    .AddPolicyHandler(HttpPolicyExtensions
        .HandleTransientHttpError()
        .WaitAndRetryAsync(
            retryCount: 3,
            sleepDurationProvider: attempt =>
                TimeSpan.FromMilliseconds(200 * Math.Pow(2, attempt))));

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
app.MapExportEndpoints();
app.MapPartitionEndpoints();
app.MapStatsEndpoints();
app.MapMetaEndpoints();
app.MapDashboardEndpoints();
app.MapContourEndpoints();

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
