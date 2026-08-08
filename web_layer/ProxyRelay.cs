using System.Text.Json;

namespace WebLayer.Endpoints;

/// <summary>
/// Общие помощники тонких прокси-эндпоинтов (dashboard → generator_service,
/// contour → contour_service): чтение identity-заголовков и тела запроса,
/// релей ответа с переводом {"detail": ...} FastAPI → {"error": ...}
/// web-слоя. Вынесено, чтобы прокси к разным upstream'ам не дублировали
/// одну и ту же обвязку.
/// </summary>
internal static class ProxyRelay
{
    /// <summary>
    /// Личность запроса целиком: заверенная (Authorization: Bearer) и
    /// заявленная (X-User-Id / X-User-Role).
    ///
    /// Authorization здесь главный: по нему FastAPI сам смотрит, кто это и
    /// какая у него роль. X-* остаются на время перехода — их ещё шлёт
    /// десктоп — и перестанут что-либо значить, когда на сервере снимут
    /// GEN_TRUST_IDENTITY_HEADERS. До этого шага роль приходила из браузера
    /// и сервер ей верил, чего хватало, чтобы назначить себя админом.
    /// </summary>
    public static (string? uid, string? role, string? auth) Identity(HttpRequest req) =>
        (req.Headers["X-User-Id"].FirstOrDefault(),
         req.Headers["X-User-Role"].FirstOrDefault(),
         req.Headers["Authorization"].FirstOrDefault());

    public static async Task<string?> ReadBodyAsync(HttpRequest req)
    {
        if (req.ContentLength is 0) return null;
        using var reader = new StreamReader(req.Body);
        var s = await reader.ReadToEndAsync();
        return string.IsNullOrWhiteSpace(s) ? null : s;
    }

    /// <summary>
    /// 2xx — тело как есть. Иначе {"detail": ...} FastAPI → {"error": ...}
    /// web-слоя (тот же контракт, что читает фронтовый ApiError).
    /// </summary>
    public static IResult Relay(int status, string body)
    {
        if (status is >= 200 and < 300)
            return Results.Content(body, "application/json", statusCode: status);

        var error = "Ошибка сервиса";
        try
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("detail", out var d))
                error = d.ValueKind == JsonValueKind.String ? d.GetString() ?? error : d.ToString();
        }
        catch
        {
            // тело не JSON — оставляем общий текст
        }
        return Results.Json(new { error }, statusCode: status);
    }
}
