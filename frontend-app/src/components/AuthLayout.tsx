import { FlaskConical } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

/** Props for one step of the staggered entrance animation (CSS only, honours reduced motion). */
export function enter(index: number, className = "", style?: CSSProperties): { className: string; style: CSSProperties } {
  return {
    className: className ? `auth-enter ${className}` : "auth-enter",
    style: { "--i": index, ...style } as CSSProperties,
  };
}

/** Two-column layout shared by the login and registration screens. */
export function AuthLayout({
  title,
  lead,
  features,
  children,
}: {
  title: string;
  lead: string;
  features: string[];
  children: ReactNode;
}) {
  return (
    <main className="auth-page">
      <section className="auth-brand">
        <div className="brand">
          <span className="brand-mark">
            <FlaskConical size={19} aria-hidden="true" />
          </span>
          <span>LabOnDemand</span>
        </div>
        <div className="auth-copy">
          <h1>{title}</h1>
          <p className="muted">{lead}</p>
          <ul className="auth-list">
            {features.map((feature) => (
              <li key={feature}>
                <span>{feature}</span>
              </li>
            ))}
          </ul>
        </div>
        <span className="muted">© {new Date().getFullYear()} LabOnDemand</span>
      </section>

      <section className="auth-form-panel">{children}</section>
    </main>
  );
}
