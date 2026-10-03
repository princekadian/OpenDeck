import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./diagnostics/ErrorBoundary";
import { installGlobalErrorReporting } from "./diagnostics/errorReporting";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/key.css";

installGlobalErrorReporting();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
