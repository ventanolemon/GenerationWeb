import { Component, type ReactNode, type ErrorInfo } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catch'ит непойманные исключения из дерева компонентов. Это safety-net,
 * а не полноценный error handling — реальные ошибки запросов мы ловим
 * в самих view-компонентах через try/catch.
 *
 * Без этого один сломавшийся блок (например, неизвестный type, который
 * мы не предусмотрели) уронил бы всё приложение в whitescreen.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Логируем — в dev-консоль или в Sentry/иную систему.
    console.error("Unhandled error in component tree:", error, info);
  }

  override render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: "2rem",
            background: "#fee",
            color: "#900",
            fontFamily: "system-ui",
          }}
        >
          <h2>Что-то пошло не так</h2>
          <pre style={{ whiteSpace: "pre-wrap" }}>
            {this.state.error.message}
          </pre>
          <button onClick={() => this.setState({ error: null })}>
            Попробовать снова
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
