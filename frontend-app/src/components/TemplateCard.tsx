import { Rocket } from "lucide-react";
import { motion } from "motion/react";
import type { Template } from "../types/api";
import { RuntimeIcon } from "../lib/icons";
import { useI18n } from "../lib/i18n";
import { Button } from "./ui";

export function TemplateCard({
  template,
  index = 0,
  onSelect,
}: {
  template: Template;
  index?: number;
  onSelect: (template: Template) => void;
}) {
  const { locale } = useI18n();
  const deploymentType = template.deployment_type || template.key || String(template.id || "custom");
  return (
    <motion.article
      className="card template-card !flex flex-col gap-3"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, delay: Math.min(index, 8) * 0.05, ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="template-card-head">
        <div className="template-title">
          <span className="runtime-mark">
            <RuntimeIcon type={deploymentType} />
          </span>
          <div className="min-w-0">
            <strong>{template.name || template.key}</strong>
            <div className="muted code-text text-[0.78rem]">{deploymentType}</div>
          </div>
        </div>
      </div>
      <p className="muted leading-relaxed flex-1">
        {template.description || (locale === "fr" ? "Template Kubernetes prêt à déployer." : "Kubernetes template ready to deploy.")}
      </p>
      <div className="template-meta">
        {template.default_image ? <span className="badge truncate-cell" title={template.default_image}>{template.default_image}</span> : null}
        {template.default_port ? <span className="badge">Port {template.default_port}</span> : null}
        {(template.tags || []).map((tag) => (
          <span className="badge blue" key={tag}>
            {tag}
          </span>
        ))}
      </div>
      <div className="actions-row mt-auto">
        <Button variant="primary" className="w-full" onClick={() => onSelect(template)}>
          <Rocket size={16} />
          {locale === "fr" ? "Lancer" : "Launch"}
        </Button>
      </div>
    </motion.article>
  );
}
