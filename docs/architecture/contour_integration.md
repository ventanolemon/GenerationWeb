# Интеграция LLM-контура в топологию

`Generator/docs/closed_loop_contract.md` определяет ЧТО происходит
(S0–S6, бюджеты V=3/R=2, инварианты); этот документ — ГДЕ это живёт и
как дёргается. Контракт петли не пересматривается.

## 1. Владелец: contour_service

Петлёй владеет `contour_service` (обоснование выбора процесса — в
`system_topology.md` §3). Стадии распределяются так:

| Стадия | Чем исполняется |
|---|---|
| S0 заземление | contour_service: выгрузка каталога из `NodeRegistry` (импорт core) + few-shot retrieval из `corpus_records` |
| S1 генерация | провайдер `llm.generate_graph` из реестра нейропровайдеров |
| S2 сборка / S3 probe / S4 SYM-флаги | ИМПОРТ `core/graph` (GraphExecutor + probe) — не сеть |
| S5 критик | провайдер `llm.critic` |
| S6 человек | UI через web_layer (см. §4) |

Агенты петли — те же провайдеры реестра, что и «нейросети для
произношения»: одна абстракция на всё нечёткое.

## 2. Жизненный цикл джобы

```mermaid
sequenceDiagram
    participant T as Преподаватель (web/desktop)
    participant WL as web_layer
    participant CS as contour_service
    participant PG as Postgres
    participant LLM as LLM-провайдеры

    T->>WL: POST /api/contour/jobs {description, subject_id}
    WL->>WL: RBAC: role ≥ teacher
    WL->>CS: создать джобу
    CS->>PG: INSERT contour_jobs (status=queued)
    CS-->>T: 202 {job_id}
    loop воркер (FOR UPDATE SKIP LOCKED)
        CS->>LLM: S1 (или repair-раунд)
        CS->>CS: S2–S4 импортом движка
        CS->>PG: append раунда в rounds; corpus_records при событиях
        CS->>LLM: S5 критик
    end
    CS->>PG: status=awaiting_human
    T->>WL: GET /api/contour/jobs/{id} (поллинг 2–5 с)
    WL-->>T: {status, превью заданий, warn-флаги, summary критика}
    T->>WL: POST /api/contour/jobs/{id}/approve
    WL->>CS: утвердить
    CS->>PG: партиция constracted=4 + corpus: human.approved=true
```

Статусы: `queued → generating → validating → critic → awaiting_human →
approved | rejected | escalated | failed`. Смена статуса и персист
артефактов раунда — одна транзакция (поэтому очередь в Postgres, а не
брокер).

## 3. Персист = сбор корпуса (бесплатный)

Прямое отображение §5 контракта петли на таблицы:

| Событие петли | Запись |
|---|---|
| принято человеком (S6 approve) | `corpus_records(kind=generate)` — по `training_example_schema.json`, `human.approved=true` |
| успешный repair-раунд | `corpus_records(kind=repair)` — битый граф + дословные ошибки + починенный |
| эскалация (V или R исчерпаны) | `corpus_records(kind=escalation)` — полный лог; не для обучения, для статистики тем |
| каждый раунд | `contour_jobs.rounds` JSONB — полная история для экрана S6 и отладки |

`graph_hash` (канонический: топосорт → переименование id → sha256, из
training_plan.md) пишется при вставке — дедуп корпуса это `UNIQUE`-чек,
а не пост-обработка.

## 4. S6 — флоу утверждения (роли и экраны, не пиксели)

- Джобы `awaiting_human` видит АВТОР джобы (teacher) и admin — раздел
  «На утверждении». Чужие джобы teacher не видит и не утверждает.
- Экран: описание запроса; 3–5 превью заданий (блоки `to_dict()` →
  существующий BlockRenderer; это тот же формат, что `/graph/preview`);
  warn-флаги SYM-проб; summary и confidence критика; история раундов
  (сворачиваемая).
- Действия:
  - **Принять** → contour_service создаёт партицию (владелец = автор
    джобы) + помечает корпусную запись `human.approved`.
  - **Открыть в редакторе** → граф передаётся в граф-редактор клиента;
    дальше обычное сохранение партиции; корпусная запись помечается
    `human_edited` (для обучения такие пары ценны отдельно).
  - **Отклонить** (с причиной) → `rejected`, причина в лог эскалаций.
- Партиция НИКОГДА не создаётся без S6 — инвариант №5 контракта
  переносится сюда дословно.

## 5. Отказы и повторность

- Рестарт воркера посреди раунда: джоба остаётся залоченной до конца
  транзакции; незакоммиченный раунд исчезает — воркер повторит его
  (идемпотентно: LLM-вызов повторяется, бюджеты считаются по
  закоммиченным раундам).
- Недоступность LLM-провайдера: джоба → `failed` с ошибкой провайдера
  после N ретраев; НЕ жжёт бюджет V (это не ошибка графа).
- Таймаут джобы целиком (конфиг, например 15 мин) → `failed`; стоимость
  токенов на джобу — тоже бюджет из контракта, отчёт в `rounds`.
