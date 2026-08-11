import type { LucideIcon } from "lucide-react";

type EmptyModuleProps = Readonly<{
  description: string;
  icon: LucideIcon;
  phase: string;
  title: string;
}>;

export const EmptyModule = ({ description, icon: Icon, phase, title }: EmptyModuleProps) => (
  <article className="empty-module">
    <span className="empty-module__icon">
      <Icon aria-hidden="true" size={19} strokeWidth={1.7} />
    </span>
    <div>
      <span className="eyebrow">{phase}</span>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  </article>
);
