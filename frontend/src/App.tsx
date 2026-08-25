import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";

import { Analysis } from "./pages/analysis";
import { Etf } from "./pages/etf";
import { Gate } from "./pages/gate";
import { Market } from "./pages/market";
import { Overview } from "./pages/overview";
import { Showcase } from "./pages/showcase";
import { Strategy } from "./pages/strategy";
import { Trading } from "./pages/trading";

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
  if (pathname === "/gate") {
    return <Gate />;
  }
  if (pathname === "/trading") {
    return <Trading />;
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
