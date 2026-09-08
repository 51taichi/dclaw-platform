import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./i18n";
import "./styles/animations.css";
import { installHostExternals } from "./plugins/hostExternals";
import { registerHostModulesEager } from "./plugins/dynamicModuleRegistry";
import { DesktopUpdateGate } from "./components/DesktopUpdateChecker";
import { installDesktopHttpGate } from "./desktop/httpGate";

// Expose host dependencies (React, antd, etc.) on window
// so that plugin UI modules can use them without bundling their own copies.
installHostExternals();

// Dynamic module registration - no generated files needed!
// Automatically discovers all modules in src/pages at build time
registerHostModulesEager();

if (typeof window !== "undefined") {
  const originalError = console.error;
  const originalWarn = console.warn;

  console.error = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    if (msg.includes(":first-child") || msg.includes("pseudo class")) {
      return;
    }
    originalError.apply(console, args as []);
  };

  console.warn = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    if (
      msg.includes(":first-child") ||
      msg.includes("pseudo class") ||
      msg.includes("potentially unsafe")
    ) {
      return;
    }
    originalWarn.apply(console, args as []);
  };
}

void installDesktopHttpGate()
  .catch(() => undefined)
  .finally(() => {
    createRoot(document.getElementById("root")!).render(
      <DesktopUpdateGate>
        <App />
      </DesktopUpdateGate>,
    );
  });
