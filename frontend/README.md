# frontend — React + Vite

Веб-UI генератора заданий. Соответствует трём другим слоям монорепо:
core (Python-ядро), generator_service (FastAPI), web_layer (ASP.NET).

## Структура

```
frontend/
├── index.html                        — точка входа Vite
├── vite.config.ts                    — конфиг Vite + dev-прокси /api → :5000
├── tsconfig.json, tsconfig.app.json  — настройки TypeScript (strict mode)
├── package.json                      — React 18 + Vite 5 + TypeScript 5
│
├── src/
│   ├── main.tsx                      — bootstrap, ErrorBoundary, <App />
│   ├── App.tsx                       — layout, выбор предмета и раздела, диспатч view
│   ├── vite-env.d.ts                 — типы для CSS-модулей и Vite
│   │
│   ├── api/
│   │   ├── client.ts                 — fetch-обёртка с обработкой ошибок
│   │   └── types.ts                  — TS-зеркало DTO из C# и FastAPI
│   │
│   ├── blocks/                       ←─ КЛЮЧЕВАЯ ЧАСТЬ
│   │   ├── BlockRenderer.tsx         — единая точка рендера, диспатчит по type
│   │   ├── registry.ts               — мапа type → React-компонент
│   │   ├── TextBlock.tsx
│   │   ├── FormulaBlock.tsx          — base64-PNG из ядра + LaTeX fallback
│   │   ├── ImageBlock.tsx
│   │   ├── CodeBlock.tsx
│   │   ├── TableBlock.tsx
│   │   ├── FillInBlankBlock.tsx      — поля ввода + подсветка по мере набора
│   │   └── WordCorrectionBlock.tsx   — diff-рендер без HTML
│   │
│   ├── views/
│   │   ├── StaticTaskView.tsx        — одно задание + ответ + экспорт
│   │   ├── TableTaskView.tsx         — таблица накопленных заданий
│   │   ├── TestExportView.tsx        — N вариантов теста в табах
│   │   └── InteractiveTaskView.tsx   — сессия диалога с историей
│   │
│   ├── components/
│   │   ├── SubjectPicker.tsx
│   │   ├── PartitionList.tsx
│   │   └── ErrorBoundary.tsx
│   │
│   └── styles/                       — CSS-модули
│       ├── global.css
│       ├── app.module.css
│       ├── sidebar.module.css
│       ├── views.module.css
│       └── blocks.module.css
│
└── README.md
```

## Архитектурное ядро: полиморфный рендерер блоков

Каждый блок задачи приходит из ядра как JSON-объект с полем `type`
и доп. полями, специфичными для типа. Фронт рендерит его так:

```tsx
// blocks/BlockRenderer.tsx
export default function BlockRenderer({ block }: { block: Block }) {
  if (!hasRenderer(block)) {
    return <UnknownBlockFallback type={block.type} />;
  }
  const Component = blockComponents[block.type];
  return <Component block={block} />;
}
```

И — точка. `blockComponents` — это `Record<string, ComponentType>`, импорты
конкретных компонентов лежат рядом в `registry.ts`. **Во всём фронте нет ни
одного `switch` по `block.type` или эквивалента `isinstance`.**

Это тот же принцип, что мы провели через все четыре слоя:

| Слой               | Полиморфизм        | Реализация            |
|--------------------|--------------------|-----------------------|
| Ядро               | `Block.to_dict()`  | 4-й метод абстракции  |
| generator_service  | `return task.to_dict()` | без сериализаторов |
| web_layer (C#)     | `JsonElement`      | без `BlockDto`        |
| frontend (React)   | `blockComponents`  | без `switch`          |

**Добавление нового типа блока** (например, граф или аудио): создать
`*.tsx`-компонент, дописать одну строку в `registry.ts`, добавить тип
в discriminated union в `types.ts`. Все остальные view-компоненты
получают его автоматически.

## Контракт между фронтом и Web Layer

Все запросы под префиксом `/api`. В dev-режиме Vite проксирует их на
ASP.NET (`http://localhost:5000`), см. `vite.config.ts`. В production
фронт раздаётся тем же сервером — относительные URL работают везде.

| Метод и путь                         | Когда вызывается                |
|--------------------------------------|---------------------------------|
| `GET /api/subjects`                  | при старте App                  |
| `GET /api/subjects/{id}/partitions`  | при смене предмета              |
| `POST /api/generate`                 | кнопка «Сгенерировать»          |
| `POST /api/interactive/submit`       | каждый ответ в тренажёре        |
| `POST /api/export`                   | кнопка «Экспорт в Word»         |

DTO в `src/api/types.ts` — точное TypeScript-зеркало того, что выдаёт
ASP.NET (и через него — FastAPI). Поля приходят в snake_case
(`image_b64`, `view_kind`, ...) — это сознательно: C#-слой их не
перепаковывает в camelCase, чтобы контракт совпадал по всем трём
языкам до символа.

## Запуск

Перед стартом фронта должны быть запущены:
1. `generator_service` (FastAPI) на `:8000`
2. `web_layer` (ASP.NET) на `:5000`

Сам фронт:

```bash
cd frontend
npm install
npm run dev
```

Vite поднимется на `http://localhost:5173`. Запросы к `/api/*`
автоматически проксируются на ASP.NET (Vite proxy в `vite.config.ts`).

## Проверка локально

```bash
# Type-check (strict, без emit)
npm run typecheck

# Production build
npm run build

# Preview собранного билда
npm run preview
```

## Архитектурные решения и их обоснования

### Без state-менеджера (Redux/Zustand)

Четыре экрана, одна сессия — `useState` + локальный state дочерних
компонентов справляется. Когда добавится управление разделами (создание
групп/тестов через UI, как в десктопе) или коллаборативные сессии —
переедем на Zustand. Сейчас redux был бы overkill ради эстетики.

### Без UI-фреймворка (MUI/AntD)

Для четырёх view-компонентов и семи блок-компонентов фреймворк — лишний
вес (полтонны JS, несвязанные стили). CSS-модули дают предсказуемые
имена классов и scope. Если когда-то понадобится комплексный
date-picker или drag-and-drop редактор тестов — добавлю Radix UI
точечно, без миграции всего проекта.

### Сессия только в локальном state

`InteractiveTaskView` хранит `sessionId`, `prompt`, `history` и `score`
в `useState`. При перезагрузке страницы сессия теряется на фронте,
а в FastAPI она ещё какое-то время живёт по TTL. Это сознательное
упрощение для MVP: persistance сессий между перезагрузками —
отдельная история (нужен `sessionStorage`, восстановление через
`/api/interactive/state` — а такого эндпоинта пока нет).

### Discriminated union для блоков на TypeScript

```ts
export type Block =
  | TextBlock         // type: "text"
  | FormulaBlock      // type: "formula"
  | ...
  | { type: string; [key: string]: unknown };  // fallback
```

Сужение типа по `block.type` в каждом конкретном рендерере проверяется
компилятором. Последний вариант (`type: string`) нужен, чтобы фронт
не падал на блоках, добавленных в ядро уже после деплоя фронта —
`BlockRenderer` для них покажет fallback с пометкой типа.

### `is_interactive` пришёл с бэка, не считается на фронте

Изначально я хотел разруливать выбор `InteractiveTaskView` через
эвристику «если subject_id == 2, значит интерактив». Поймал себя на
том, что это знание о конкретном предмете в коде фронта — ровно то,
что запрещено стандартом проекта. Поэтому добавил поле `is_interactive`
в ответ FastAPI `/subjects/{id}/partitions` (правка в трёх файлах
одним коммитом: FastAPI, C#-DTO, TS-тип). Фронт теперь работает с
любыми будущими интерактивными модулями без правок.

## Сборка для production

`npm run build` даёт:
* `dist/index.html` (~0.4 КБ)
* `dist/assets/index-*.css` (~6 КБ, 2 КБ gzipped)
* `dist/assets/index-*.js` (~160 КБ, 52 КБ gzipped)

Это полный фронт без UI-фреймворка. Можно раздавать любым статическим
сервером — Nginx, ASP.NET-статикой через `app.UseStaticFiles()`, или
просто прицепить `dist/` к web_layer как `wwwroot/`.

## Что НЕ сделано (тех-долг)

* **Управление разделами через UI**. В десктопе есть редакторы группы,
  теста и физического конструктора (`ui/editors/`). В вебе — нет.
  Это самая крупная отсутствующая фича; FastAPI и Web Layer для её
  поддержки нужно расширить (POST/PUT/DELETE на /api/partitions).
* **Аутентификация и регистрация**. Нет ни форм входа, ни хранения
  user_id. Все запросы анонимные, межсессионная статистика
  словарного тренажёра — гостевая (in-memory на инстанс FastAPI).
* **Persistance сессий через перезагрузку**. `sessionStorage` под
  `sessionId` + восстановление prompt при возврате на страницу.
* **Подсветка синтаксиса в `CodeBlock`**. Сейчас просто моноширинный
  шрифт. Можно добавить `highlight.js` одним местом, но для задачи
  «найти ошибки в C-коде» без подсветки даже честнее — пользователь
  не получает подсказку от подсветки.
* **Тесты компонентов**. Не написаны (vitest + @testing-library/react).
  Контракт с бэком и логика блоков покрыты тестами в `generator_service`
  и `web_layer`, но React-компоненты — нет.
* **Доступность (a11y)**. Базовые roles и aria-labels есть в части
  компонентов, но систематической проверки нет.
* **Адаптив для мобильных**. Layout рассчитан на десктоп (sidebar
  280px фиксирован). На мобильном будет горизонтальный скролл.
