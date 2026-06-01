import type { Template } from "../types/api";
import { RuntimeIcon } from "../lib/icons";
import { useI18n } from "../lib/i18n";
import { Button } from "./ui";

export function TemplateCard({ template, onSelect }: { template: Template; onSelect: (template: Template) => void }) {
  const { locale } = useI18n();
  const deploymentType = template.deployment_type || template.key || String(template.id || "custom");
  return (
    <article className="card template-card">
      <div className="template-card-head">
        <div className="template-title">
          <span className="runtime-mark">
            <RuntimeIcon type={deploymentType} />
          </span>
          <div>
            <strong>{template.name || template.key}</strong>
            <div className="muted">{deploymentType}</div>
          </div>
        </div>
      </div>
      <p className="muted">
        {template.description || (locale === "fr" ? "Template Kubernetes prêt à déployer." : "Kubernetes template ready to deploy.")}
      </p>
      <div className="template-meta">
        {template.default_image ? <span className="badge truncate-cell" title={template.default_image}>{template.default_image}</span> : null}
        {template.default_port ? <span className="badge">Port {template.default_port}</span> : null}
        {(template.tags || []).map((tag) => (
          <span className="badge" key={tag}>
            {tag}
          </span>
        ))}
      </div>
      <div className="actions-row">
        <Button variant="primary" onClick={() => onSelect(template)}>
          {locale === "fr" ? "Lancer" : "Launch"}
        </Button>
      </div>
    </article>
  );
}
