import { Info, LockKeyhole, OctagonAlert } from "lucide-react";

type BannerLevel = "danger" | "info" | "warning";

type SafetyBannerProps = Readonly<{
  code?: string;
  description: string;
  level: BannerLevel;
  title: string;
}>;

const icons = {
  danger: OctagonAlert,
  info: Info,
  warning: LockKeyhole,
} as const;

export const SafetyBanner = ({ code, description, level, title }: SafetyBannerProps) => {
  const Icon = icons[level];
  return (
    <section aria-label={title} className={`banner banner--${level}`} role="status">
      <span className="banner__icon">
        <Icon aria-hidden="true" size={19} strokeWidth={1.8} />
      </span>
      <div>
        <div className="banner__title">
          {title}
          {code !== undefined && <StatusCode code={code} />}
        </div>
        <p>{description}</p>
      </div>
    </section>
  );
};

const StatusCode = ({ code }: Readonly<{ code: string }>) => (
  <span className="badge badge--warn">{code}</span>
);
