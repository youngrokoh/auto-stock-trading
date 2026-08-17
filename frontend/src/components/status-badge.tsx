type BadgeKind = "accent" | "danger" | "down" | "neutral" | "ok" | "up" | "warn";

type StatusBadgeProps = Readonly<{
  kind: BadgeKind;
  label: string;
}>;

export const StatusBadge = ({ kind, label }: StatusBadgeProps) => (
  <span className={kind === "neutral" ? "badge" : `badge badge--${kind}`}>{label}</span>
);
