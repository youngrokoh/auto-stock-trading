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

type ScreenKey = "overview" | "market" | "analysis";

type NavEntry = Readonly<{
  href?: string;
  icon: LucideIcon;
  key?: ScreenKey;
  label: string;
  note?: string;
}>;

const primaryNav: readonly NavEntry[] = [
  { href: "/", icon: Gauge, key: "overview", label: "운영 개요" },
  { href: "/market", icon: CandlestickChart, key: "market", label: "시장 데이터" },
  { href: "/analysis", icon: Building2, key: "analysis", label: "기업 분석" },
] as const;

const upcomingNav: readonly NavEntry[] = [
  { icon: Landmark, label: "ETF 탐색", note: "5단계" },
  { icon: FlaskConical, label: "전략 연구", note: "6단계" },
  { icon: ScrollText, label: "모의매매 콘솔", note: "7단계" },
  { icon: SlidersHorizontal, label: "설정과 감사", note: "이후" },
] as const;

const tabNav: readonly NavEntry[] = [
  { href: "/", icon: Gauge, key: "overview", label: "운영" },
  { href: "/market", icon: CandlestickChart, key: "market", label: "시장" },
  { href: "/analysis", icon: Building2, key: "analysis", label: "기업" },
  { icon: FlaskConical, label: "전략", note: "준비 중" },
  { icon: ScrollText, label: "매매", note: "준비 중" },
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
      <span className="nav__label">준비 중 단계</span>
      {upcomingNav.map((entry) => (
        <span aria-disabled="true" className="nav__item" key={entry.label}>
          {entry.label}
          <small>{entry.note}</small>
        </span>
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
