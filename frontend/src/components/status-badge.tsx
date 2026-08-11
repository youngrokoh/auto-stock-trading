type StatusKind = "disabled" | "loading" | "ok" | "unavailable" | "warning";

type StatusBadgeProps = Readonly<{
  kind: StatusKind;
  label: string;
}>;

export const StatusBadge = ({ kind, label }: StatusBadgeProps) => (
  <span className={`status-badge status-badge--${kind}`}>
    <span className="status-badge__dot" aria-hidden="true" />
    {label}
  </span>
);
