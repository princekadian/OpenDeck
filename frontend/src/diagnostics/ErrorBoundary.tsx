import { Component, type ErrorInfo, type ReactNode } from "react";
import { reportClientError } from "./errorReporting";

interface State {
  error: Error | null;
}

/** Keeps a render crash visible (and reported) instead of leaving a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportClientError(error, `React render${info.componentStack ?? ""}`);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <main className="crash" role="alert">
        <h1 className="crash__title">The dashboard stopped working</h1>
        <p className="crash__text">The error was sent to the PC log. Reload to try again.</p>
        <pre className="crash__detail">{`${error.name}: ${error.message}`}</pre>
        <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
          Reload
        </button>
      </main>
    );
  }
}
