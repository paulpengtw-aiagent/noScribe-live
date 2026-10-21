import "@fontsource-variable/inter";
import "@fontsource/geist-mono/400.css";
import "@fontsource/geist-mono/500.css";
import "@fontsource/noto-sans-tc/400.css";
import "@fontsource/noto-sans-tc/500.css";
import "./index.css";
import "./easy.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "@/App";
import { EasyViewProvider } from "@/components/live/easy-toggle";
import { LocaleProvider } from "@/i18n";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LocaleProvider>
      <EasyViewProvider>
        <App />
      </EasyViewProvider>
    </LocaleProvider>
  </StrictMode>,
);
