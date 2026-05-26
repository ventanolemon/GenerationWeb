# web_layer — ASP.NET Core Web Layer

Тонкий .NET 8 Web API между React-фронтом и FastAPI generator_service.
Минимальный API без MVC и без аутентификации (для MVP).

## Структура

```
web_layer/
├── WebLayer.csproj
├── Program.cs                        ← Сборка приложения, DI, CORS, Polly
├── appsettings.json                  ← URL FastAPI, кеш-TTL, CORS origins
├── appsettings.Development.json      ← переопределения для разработки
├── Properties/
│   └── launchSettings.json
│
├── Contracts/
│   ├── Requests.cs                   ← DTO от фронта: GenerateRequest, SubmitRequest, ExportRequest
│   └── Responses.cs                  ← DTO с FastAPI: SubjectDto, PartitionDto, ...
│
├── Services/
│   └── GeneratorClient.cs            ← Typed HttpClient к FastAPI
│
├── Endpoints/
│   ├── SubjectsEndpoints.cs          ← GET /api/subjects, /api/subjects/{id}/partitions
│   ├── GenerateEndpoints.cs          ← POST /api/generate
│   ├── InteractiveEndpoints.cs       ← POST /api/interactive/submit
│   ├── ExportEndpoints.cs            ← POST /api/export
│   └── MetaEndpoints.cs              ← GET /api/health
│
├── README.md
└── .gitignore
```

## Архитектурные решения

### Блоки как `JsonElement`

В исходном архитектурном плане предлагался `BlockDto` с десятком nullable-полей
(`Content`, `Latex`, `ImageB64`, `Code`, `Language`, `Rows`, ...). Я от этого
отказался по двум причинам:

1. **Нарушение стандарта проекта**. Стандарт ядра запрещает `isinstance`-каскады
   снаружи. С точки зрения C#-слоя такой `BlockDto` — это и есть скрытый каскад:
   код, который его собирает, обязан знать обо всех типах блоков. При добавлении
   нового блока (`GraphBlock`, `AudioBlock`) пришлось бы править C#-DTO.

2. **Лишний костыль**. Блоки сериализуются ядром в безопасный JSON через
   `Block.to_dict()` (шаг 1). На фронте React-компонент `<BlockRenderer>`
   разбирает блок по полю `"type"`. C#-слою совершенно нечего с этим делать —
   он просто пробрасывает JSON-структуру дальше.

Поэтому `StaticTaskResponse.Statement`, `TurnResultResponse.Feedback` и т.п. —
это `JsonElement`. C# гарантирует только то, что внешняя оболочка задачи
(тип, partition_id, session_id, флаги) типизирована и валидируема.

### Кеш справочников

`IMemoryCache` с TTL из конфига. Subjects кешируем 5 минут — они в БД меняются
крайне редко. Partitions — минуту, потому что пользователь может создать группу
или тест прямо из UI (этот функционал есть в десктопе и появится в вебе на
шаге 4); хочется, чтобы изменения подхватывались быстро.

Кеш не инвалидируется явно. Когда добавится управление разделами, инвалидация
конкретного ключа `partitions:{subjectId}` после mutation станет нужна. Сейчас
полагаемся на короткий TTL.

### Polly retry

`Microsoft.Extensions.Http.Polly` с тремя ретраями и экспоненциальной задержкой
(200ms → 400ms → 800ms). Срабатывает на 5xx и сетевых сбоях. Это страхует
от типичного кейса: FastAPI перезапускается, ASP.NET попадает на короткое
окно недоступности. Без retry первый запрос фронта при холодном старте упал бы
с 500.

### Без аутентификации

Сознательное упрощение для MVP, отмечено в архитектурном плане как
тех-долг. Когда понадобится:
* добавить cookie-based session или JWT (`AddAuthentication`);
* в `GeneratorClient` пробрасывать `user_id` в заголовке `X-User-Id`;
* в FastAPI читать заголовок и пробрасывать в `WordsTrainerGenerator.user_id_provider`.

## Конфигурация (`appsettings.json`)

```jsonc
{
  "Generator": {
    "BaseUrl": "http://127.0.0.1:8000",   // куда стучаться к FastAPI
    "TimeoutSeconds": 30
  },
  "Cors": {
    "AllowedOrigins": [
      "http://localhost:5173"             // Vite dev server (шаг 4)
    ]
  },
  "Cache": {
    "SubjectsSeconds": 300,
    "PartitionsSeconds": 60
  }
}
```

В `appsettings.Development.json` добавлен `http://127.0.0.1:5173` (некоторые
браузеры рассматривают localhost и 127.0.0.1 как разные origin'ы).

## API — контракт для фронта

Все эндпоинты под префиксом `/api`. Возвращают `application/json` (кроме `/api/export`).

### GET /api/subjects

```json
[
  {"id": 1, "name": "Линейная алгебра", "parent_name": "Линейная алгебра"}
]
```

### GET /api/subjects/{id}/partitions

```json
[
  {
    "id": 40, "subject_id": 10, "name": "Обычные производные",
    "constracted": 0, "has_generator": true, "view_kind": "single"
  }
]
```

* `view_kind` — `"single"` / `"table"` / `"test"`, подсказка фронту, какой компонент рендерить.
* `has_generator` — если `false`, кнопка генерации не показывается.

### POST /api/generate

Запрос: `{"partitionId": 40}`

Ответ (статичная задача) — JSON-объект из FastAPI, прокидывается как есть:
```json
{
  "type": "static",
  "partition_id": 40,
  "statement": [
    {"type": "text", "content": "Найдите производную:"},
    {"type": "formula", "latex": "x^2", "image_b64": "iVBOR..."}
  ],
  "answer": [...],
  "meta": {"partition_id": 40}
}
```

Ответ (интерактивная задача):
```json
{
  "type": "interactive",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "partition_id": 1000,
  "prompt": [{"type": "text", "content": "..."}],
  "is_finished": false
}
```

Ошибки: 400 (невалидный partitionId), 404 (нет генератора), 502/503 (FastAPI лежит).

### POST /api/interactive/submit

Запрос: `{"sessionId": "...", "userInput": "apple"}`

Ответ:
```json
{
  "correct": true,
  "feedback": [...],
  "next_prompt": [...] | null,
  "is_finished": false
}
```

Когда `is_finished: true`, сессия завершена, фронт может предложить начать заново.

Ошибки: 400 (пустой sessionId), 404 (сессия не найдена / истёк TTL 30 мин).

### POST /api/export

Запрос: `{"partitionId": 40, "count": 5, "withAnswers": true}`

Ответ: бинарный `.docx` со заголовками
```
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; filename="tasks_40.docx"
```

Ошибки: 400 (невалидные параметры / интерактивный раздел), 404 (нет генератора).

### GET /api/health

```json
{
  "status": "ok",
  "web": "ok",
  "generator": "ok",
  "generators_count": 32
}
```

503 если FastAPI недоступен.

## Установка и запуск

Требования: .NET 8 SDK.

```bash
cd web_layer
dotnet restore
dotnet run
```

Web Layer стартует на http://localhost:5000.

Перед запуском должен быть запущен `generator_service` (шаг 2) на порту 8000.
В одном терминале:

```bash
cd <корень монорепо>
uvicorn generator_service.main:app --port 8000
```

В другом — `dotnet run` из `web_layer/`.

## Проверка вручную

```bash
# 1. Health
curl http://localhost:5000/api/health
# {"status":"ok","web":"ok","generator":"ok","generators_count":32}

# 2. Список предметов
curl http://localhost:5000/api/subjects

# 3. Разделы предмета 1
curl http://localhost:5000/api/subjects/1/partitions

# 4. Сгенерировать задание
curl -X POST http://localhost:5000/api/generate \
     -H "Content-Type: application/json" \
     -d '{"partitionId": 40}'

# 5. Скачать .docx
curl -X POST http://localhost:5000/api/export \
     -H "Content-Type: application/json" \
     -d '{"partitionId": 40, "count": 2}' \
     --output tasks.docx
```

## Чек-лист код-ревью

Шесть точек, которые рекомендую проверить при первом `dotnet build`,
потому что в среде разработки этого README не было полноценной .NET-сборки:

1. **Polly пакет.** Версия `8.0.19` совместима с .NET 8 SDK. Если у вас
   установлен только .NET 9, поднимите до `Microsoft.Extensions.Http.Polly 10.x`.
2. **Globalization.** Стоит `<InvariantGlobalization>true</InvariantGlobalization>`
   — это для маленького Docker-образа. Если запускаете в Windows и где-то
   нужно русское `CultureInfo`, уберите.
3. **Routing case.** Конфигурация эндпоинтов чувствительна к регистру:
   `/api/health`, не `/api/Health`. .NET 8 minimal API по умолчанию
   case-insensitive для route'ов, но мы зависим от точного совпадения с фронтом.
4. **CORS preflight.** `AllowCredentials()` требует точного списка origin'ов,
   не `AllowAnyOrigin()`. Если фронт начнёт стучаться с другого порта,
   добавьте его в `Cors:AllowedOrigins` в `appsettings.Development.json`.
5. **Stream lifetime в export.** Поток из `client.ExportAsync` мы отдаём в
   `Results.File`, который при отправке вызывает `Dispose()`. Поэтому
   собственный `using` нам не нужен. Если вдруг увидите `ObjectDisposedException`,
   это значит, что где-то поток закрылся раньше.
6. **JsonElement сериализация.** В ответе `/api/generate` блоки приходят как
   `JsonElement`. System.Text.Json сериализует их обратно один в один,
   сохраняя snake_case-имена полей (`image_b64`, `last_seen`, ...). Никакого
   `CamelCasePropertyNamingPolicy` мы не ставим — это специально, чтобы
   контракт совпадал с FastAPI до символа.

## Что не сделано (тех-долг)

- **Интеграционные тесты на xUnit + `WebApplicationFactory<Program>`.** Полностью
  пропущены, потому что среда подготовки этого README не имеет .NET SDK для
  их прогона. Для них в `Program.cs` уже добавлен `public partial class Program`.
  Готовая структура: `tests/WebLayer.IntegrationTests/` с `WireMock.Net` для
  мока FastAPI.
- **Open API/Swagger.** В .NET 9 он стал из коробки, в .NET 8 — через
  `Swashbuckle.AspNetCore`. Сейчас не нужно: фронт знает контракт из этого README.
- **Аутентификация.** Описано выше.
- **Rate limiting.** Можно добавить через `AddRateLimiter` из коробки в .NET 8,
  если сервис будет публичным.
- **Healthchecks по-настоящему.** Сейчас `/api/health` — просто пинг
  upstream'а. Для прода стоит использовать `Microsoft.Extensions.Diagnostics.HealthChecks`
  с двумя checks: `self` (всегда ok) и `upstream` (через GeneratorClient).
