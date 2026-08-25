import type { LucideIcon } from "lucide-react";
import {
  Building2,
  CandlestickChart,
  FlaskConical,
  Gauge,
  Landmark,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import type { ReactNode } from "react";

type ScreenKey =
  | "overview"
  | "market"
  | "analysis"
  | "etf"
  | "strategy"
  | "trading"
  | "gate"
  | "settings";

type NavEntry = Readonly<{
  href?: string;
  icon: LucideIcon;
  key?: ScreenKey;
  label: string;
}>;

const primaryNav: readonly NavEntry[] = [
  { href: "/", icon: Gauge, key: "overview", label: "운영 개요" },
  { href: "/market", icon: CandlestickChart, key: "market", label: "시장 데이터" },
  { href: "/analysis", icon: Building2, key: "analysis", label: "기업 분석" },
  { href: "/etf", icon: Landmark, key: "etf", label: "ETF 탐색" },
  { href: "/strategy", icon: FlaskConical, key: "strategy", label: "전략 연구" },
  { href: "/trading", icon: ScrollText, key: "trading", label: "모의매매 콘솔" },
  { href: "/gate", icon: ShieldCheck, key: "gate", label: "실전 전환 게이트" },
  { href: "/settings", icon: SlidersHorizontal, key: "settings", label: "설정과 감사" },
] as const;

const tabNav: readonly NavEntry[] = [
  { href: "/", icon: Gauge, key: "overview", label: "운영" },
  { href: "/market", icon: CandlestickChart, key: "market", label: "시장" },
  { href: "/analysis", icon: Building2, key: "analysis", label: "기업" },
  { href: "/etf", icon: Landmark, key: "etf", label: "ETF" },
  { href: "/strategy", icon: FlaskConical, key: "strategy", label: "전략" },
  { href: "/trading", icon: ScrollText, key: "trading", label: "매매" },
] as const;

type AppShellProps = Readonly<{
  active: ScreenKey;
  children: ReactNode;
  headerMeta?: ReactNode;
  title: string;
}>;

export const AppShell = ({ active, children, headerMeta, title }: AppShellProps) => (
  <div className="shell">
    <div className="rail" aria-hidden="true">
      <span className="rail__mark">AS</span>
      {primaryNav.map((entry) => (
        <a
          aria-current={entry.key === active ? "page" : undefined}
          aria-label={entry.label}
          className="rail__item"
          href={entry.href}
          key={entry.label}
        >
          <entry.icon size={17} strokeWidth={1.8} />
        </a>
      ))}
    </div>

    <nav className="nav" aria-label="주요 탐색">
      <p className="nav__title">AutoStock 리서치</p>
      <span className="nav__label">Workspace</span>
      {primaryNav.map((entry) => (
        <a
          aria-current={entry.key === active ? "page" : undefined}
          className="nav__item"
          href={entry.href}
          key={entry.label}
        >
          {entry.label}
        </a>
      ))}
      <div className="nav__footer">
        <ShieldCheck aria-hidden="true" size={12} strokeWidth={1.8} /> 실전 주문 비활성
      </div>
    </nav>

    <main className="work">
      <header className="work__header">
        <h1>{title}</h1>
        <div className="work__meta">{headerMeta}</div>
      </header>
      {children}
    </main>

    <nav className="tabbar" aria-label="모바일 탐색">
      {tabNav.map((entry) =>
        entry.href === undefined ? (
          <span aria-disabled="true" key={entry.label}>
            <entry.icon aria-hidden="true" size={16} strokeWidth={1.8} />
            {entry.label}
          </span>
        ) : (
          <a
            aria-current={entry.key === active ? "page" : undefined}
            href={entry.href}
            key={entry.label}
          >
            <entry.icon aria-hidden="true" size={16} strokeWidth={1.8} />
            {entry.label}
          </a>
        ),
      )}
    </nav>
  </div>
);
