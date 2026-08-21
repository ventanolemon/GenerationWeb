# Образ web_layer — ASP.NET Core, единственная дверь браузера в службы.
#
# Собирается из КОРНЯ монорепо:
#     docker build -f deploy/web_layer.Dockerfile -t generation/web .
#
# Версия платформы взята из `web_layer/WebLayer.csproj` (net10.0) и должна
# ехать за ним: рассинхрон здесь даёт ошибку сборки, а не тихую поломку,
# и это правильный исход.

FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

# Сначала только проектный файл: restore кэшируется отдельным слоем и не
# повторяется на каждую правку кода.
COPY web_layer/WebLayer.csproj web_layer/
RUN dotnet restore web_layer/WebLayer.csproj

COPY web_layer/ web_layer/
RUN dotnet publish web_layer/WebLayer.csproj \
        --configuration Release \
        --no-restore \
        --output /publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /publish ./

ENV ASPNETCORE_URLS=http://0.0.0.0:8080 \
    ASPNETCORE_ENVIRONMENT=Production \
    DOTNET_gcServer=1

# Тот же довод, что у Python-образа: работать от root незачем.
RUN useradd --system --create-home --uid 10002 generation
USER generation

EXPOSE 8080
ENTRYPOINT ["dotnet", "WebLayer.dll"]
