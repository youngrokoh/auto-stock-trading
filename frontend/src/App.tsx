import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";

import { Dashboard } from "./pages/dashboard";
import { Showcase } from "./pages/showcase";

type AppProps = Readonly<{
  queryClient: QueryClient;
}>;

export const App = ({ queryClient }: AppProps) => (
  <QueryClientProvider client={queryClient}>
    {window.location.pathname === "/showcase" ? <Showcase /> : <Dashboard />}
  </QueryClientProvider>
);
