using System.Text.Json;
using System.Text.Json.Serialization;

namespace WebLayer.Contracts;

/// <summary>
/// Subject — справочник предметов. Минимальная C#-проекция того, что
/// отдаёт FastAPI (Repository.Subject.to_dict()).
/// </summary>
public record SubjectDto(
    int Id,
    string Name,
    [property: JsonPropertyName("parent_name")] string ParentName
);

/// <summary>
/// Partition — раздел предмета. ParentSubjectId, ViewKind, HasGenerator
/// и IsInteractive — служебные поля сервиса, которые помогают фронту
/// выбрать правильный компонент рендера и решать, показывать ли кнопку
/// «Сгенерировать».
/// </summary>
public record PartitionDto(
    int Id,
    [property: JsonPropertyName("subject_id")] int SubjectId,
    string Name,
    int Constracted,
    [property: JsonPropertyName("has_generator")] bool HasGenerator,
    [property: JsonPropertyName("view_kind")] string ViewKind,
    [property: JsonPropertyName("is_interactive")] bool IsInteractive
);

/// <summary>
/// Ответ /generate для статичной задачи.
///
/// Statement и Answer — массивы блоков, прокинутые как есть из FastAPI.
/// Каждый блок — JSON-объект с полем "type" и доп. полями по типу
/// (см. core/blocks.py.to_dict). C#-слой не разбирает блоки; это задача
/// фронта.
///
/// Meta тоже JsonElement, потому что его содержимое варьируется от
/// генератора к генератору.
/// </summary>
public record StaticTaskResponse(
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("partition_id")] int PartitionId,
    [property: JsonPropertyName("statement")] JsonElement Statement,
    [property: JsonPropertyName("answer")] JsonElement Answer,
    [property: JsonPropertyName("meta")] JsonElement Meta
);

/// <summary>
/// Ответ /generate для интерактивной задачи. SessionId должен быть
/// сохранён на фронте — он нужен для всех последующих submit.
/// </summary>
public record InteractiveStartResponse(
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("session_id")] string SessionId,
    [property: JsonPropertyName("partition_id")] int PartitionId,
    [property: JsonPropertyName("prompt")] JsonElement Prompt,
    [property: JsonPropertyName("is_finished")] bool IsFinished
);

/// <summary>
/// Ответ /interactive/submit. NextPrompt == null означает завершение
/// сессии — фронт должен это видеть и отрисовать соответствующий экран.
/// </summary>
public record TurnResultResponse(
    bool Correct,
    [property: JsonPropertyName("feedback")] JsonElement Feedback,
    [property: JsonPropertyName("next_prompt")] JsonElement? NextPrompt,
    [property: JsonPropertyName("is_finished")] bool IsFinished
);

/// <summary>
/// Простой health-ответ.
/// </summary>
public record HealthResponse(string Status, int Generators);

/// <summary>
/// Данные пользователя — возвращаются после входа, регистрации и из профиля.
/// Расширенные поля (Email, About, AvatarColor, CreatedAt) появляются при
/// GET /profile; при входе могут быть пустыми строками/0.
/// </summary>
public record UserDto(
    string Login,
    string Fio,
    string Group,
    string Email = "",
    string About = "",
    [property: JsonPropertyName("avatar_color")] string AvatarColor = "",
    [property: JsonPropertyName("created_at")] double CreatedAt = 0
);

/// <summary>
/// Статистика словарного тренажёра для окна профиля.
/// Прокидывается как сырой JsonElement: структура (summary + words[])
/// разбирается на фронте, C#-слою незачем знать её детально.
/// </summary>
public record StatsResponse(
    [property: JsonPropertyName("is_guest")] bool IsGuest,
    [property: JsonPropertyName("summary")] JsonElement Summary,
    [property: JsonPropertyName("words")] JsonElement Words
);

/// <summary>
/// Данные раздела с generation_params для редактирования.
/// </summary>
public record PartitionEditDto(
    int Id,
    [property: JsonPropertyName("subject_id")] int SubjectId,
    string Name,
    int Constracted,
    [property: JsonPropertyName("generation_params")] JsonElement GenerationParams
);
