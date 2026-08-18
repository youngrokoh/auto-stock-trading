import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";

import { Analysis } from "./pages/analysis";
import { Etf } from "./pages/etf";
import { Market } from "./pages/market";
import { Overview } from "./pages/overview";
import { Showcase } from "./pages/showcase";
import { Strategy } from "./pages/strategy";

type AppProps = Readonly<{
  queryClient: QueryClient;
}>;

const screenFor = (pathname: string) => {
  if (pathname === "/market") {
    return <Market />;
  }
  if (pathname === "/analysis") {
    return <Analysis />;
  }
  if (pathname === "/etf") {
    return <Etf />;
  }
  if (pathname === "/strategy") {
    return <Strategy />;
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
