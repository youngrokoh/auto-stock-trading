import { QueryClient } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { startDevelopmentTools } from "./devtools";
import "./styles.css";

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("Root element is missing");
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: false,
      staleTime: 15_000,
    },
  },
});

void startDevelopmentTools();

createRoot(rootElement).render(
  <StrictMode>
    <App queryClient={queryClient} />
  </StrictMode>,
);
