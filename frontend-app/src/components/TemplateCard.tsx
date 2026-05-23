import type { Template } from "../types/api";
import { RuntimeIcon } from "../lib/icons";
import { Button } from "./ui";

export function TemplateCard({ template, onSelect }: { template: Template; onSelect: (template: Template) => void }) {
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
      <p className="muted">{template.description || "Template Kubernetes pret a deployer."}</p>
      <div className="template-meta">
        {(template.tags || []).map((tag) => (
          <span className="badge" key={tag}>
            {tag}
          </span>
        ))}
      </div>
      <div className="actions-row">
        <Button variant="primary" onClick={() => onSelect(template)}>
          Lancer
        </Button>
      </div>
    </article>
  );
}
