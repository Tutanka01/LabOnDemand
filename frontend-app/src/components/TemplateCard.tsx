import { Rocket } from "lucide-react";
import type { Template } from "../types/api";
import { RuntimeIcon } from "../lib/icons";
import { useI18n } from "../lib/i18n";
import { Button } from "./ui";

export function TemplateCard({
  template,
  onSelect,
}: {
  template: Template;
  index?: number;
  onSelect: (template: Template) => void;
}) {
  const { locale } = useI18n();
  const deploymentType = template.deployment_type || template.key || String(template.id || "custom");
  return (
    <article className="card template-card !flex flex-col gap-3">
      <div className="template-card-head">
        <div className="template-title">
          <span className="runtime-mark">
            <RuntimeIcon type={deploymentType} />
          </span>
          <div className="min-w-0">
            <strong>{template.name || template.key}</strong>
            <div className="muted code-text">{deploymentType}</div>
          </div>
        </div>
      </div>
      <p className="muted flex-1">
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
      <div className="actions-row mt-auto">
        <Button className="w-full" onClick={() => onSelect(template)}>
          <Rocket size={15} />
          {locale === "fr" ? "Lancer" : "Launch"}
        </Button>
      </div>
    </article>
  );
}
