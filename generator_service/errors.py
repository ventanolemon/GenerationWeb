"""
Единый конверт ошибки сервиса.

До этого ошибки выходили в двух видах: FastAPI отдавал `{"detail": ...}`,
web_layer — `{"error": "строка"}`. Внутри это терпимо, наружу — нет:
интеграция не может разбирать два формата и не может отличить «неверный
ключ» от «нет такого раздела», когда и то и другое приезжает свободным
текстом. Публичный API начинается с одного конверта, и вводить его надо
ДО версионирования — потом он ломается вместе с версией.

Конверт:

```jsonc
{
  "error": { "code": "not_found",        // машинно-читаемый, стабильный
             "message": "…",             // человеку
             "request_id": "…" },        // для корреляции с логами
  "detail": "…"                          // ← совместимость, см. ниже
}
```

**Почему `detail` остаётся.** Десктопные клиенты (`core/grants/client.py`,
AdminClient) читают из тела именно `detail` — выкинуть поле значило бы
оставить пользователя с «HTTP 403» вместо объяснения. Оно дублирует
`error.message` и помечено устаревшим: новые клиенты читают `error`, старые
доживают на `detail`. Убрать — отдельным шагом, когда десктоп обновится.

`request_id` берётся из заголовка `X-Request-Id`, если его прислал вызывающий
(тогда сквозная корреляция с логом web_layer работает сама), иначе
генерируется здесь. Он же уходит в ответ тем же заголовком.
"""

from __future__ import annotations
import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"

# HTTP-статус → стабильный код ошибки. Коды — часть контракта: их читают
# машины, и менять их нельзя без смены версии API.
_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}


def code_for(status: int) -> str:
    if status in _CODES:
        return _CODES[status]
    return "client_error" if 400 <= status < 500 else "server_error"


def request_id(request: Request) -> str:
    """Идентификатор запроса: пришедший снаружи или новый."""
    incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
    return incoming or str(uuid.uuid4())


def envelope(
    status: int, message: str, rid: str, **extra: Any,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code_for(status),
        "message": message,
        "request_id": rid,
    }
    error.update(extra)
    return JSONResponse(
        status_code=status,
        # detail — устаревшее зеркало message для десктопных клиентов.
        content={"error": error, "detail": message},
        headers={REQUEST_ID_HEADER: rid},
    )


def install(app: FastAPI) -> None:
    """Подключить обработчики к приложению. Идемпотентно по смыслу."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        # exc.detail у FastAPI — обычно строка, но может быть и структурой:
        # приводим к тексту, конверт обещает message строкой.
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return envelope(exc.status_code, message, request_id(request))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # Ошибки валидации остаются машинно-читаемыми целиком (поле, тип,
        # позиция) — по свободному тексту клиент не починит свой запрос.
        # errors() содержит не-JSON значения (исключения в ctx), поэтому
        # сериализуем через str().
        fields = [
            {"loc": [str(p) for p in e.get("loc", ())],
             "type": e.get("type", ""),
             "message": e.get("msg", "")}
            for e in exc.errors()
        ]
        return envelope(422, "Запрос не прошёл валидацию.",
                        request_id(request), fields=fields)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Необработанное исключение наружу уходит без подробностей — они
        # уходят в лог. Наружу отдавать трассировку нельзя: это и утечка
        # внутреннего устройства, и бесполезный для клиента текст.
        rid = request_id(request)
        logger.exception("Необработанная ошибка (request_id=%s)", rid)
        return envelope(500, "Внутренняя ошибка сервиса.", rid)
