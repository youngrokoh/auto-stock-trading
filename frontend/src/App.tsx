import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";

import { Market } from "./pages/market";
import { Overview } from "./pages/overview";
import { Showcase } from "./pages/showcase";

type AppProps = Readonly<{
  queryClient: QueryClient;
}>;

const screenFor = (pathname: string) => {
  if (pathname === "/market") {
    return <Market />;
  }
  if (pathname === "/showcase") {
    return <Showcase />;
  }
  return <Overview />;
};

export const App = ({ queryClient }: AppProps) => (
  <QueryClientProvider client={queryClient}>
    {screenFor(window.location.pathname)}
  </QueryClientProvider>
);
