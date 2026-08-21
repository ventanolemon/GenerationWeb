# Сборка веб-клиента. На выходе — статика, которую раздаёт nginx.
#
# Собирается из КОРНЯ монорепо (контекст нужен шире, чем `frontend/`:
# база знаний собирается из `docs/guide`):
#     docker build -f deploy/frontend.Dockerfile -t generation/frontend .
#
# Клиент — статика без своего сервера, и это не упрощение: база знаний
# вкомпилирована в сборку (`src/guide/content.json`), поэтому открывается
# у гостя и без сети. Со службами клиент говорит только через `/api`,
# который nginx уводит в web_layer.

FROM node:20-slim AS build
WORKDIR /app

# Зависимости отдельным слоем: правка кода не повторяет npm ci.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
# Конфигурация раздачи и проксирования — одна на весь контур.
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
