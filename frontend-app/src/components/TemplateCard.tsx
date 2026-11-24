import { Rocket } from "lucide-react";
import type { Template } from "../types/api";
import { RuntimeIcon } from "../lib/icons";
import { useI18n } from "../lib/i18n";
import { Button } from "./ui";

export function TemplateCard({
  template,
  onSelect,
  technical = true,
}: {
  template: Template;
  index?: number;
  onSelect: (template: Template) => void;
  /** Show the image and port (useful to teachers and admins, noise for students). */
  technical?: boolean;
}) {
  const { t } = useI18n();
  const deploymentType = template.deployment_type || template.key || String(template.id || "custom");
  const name = template.name || template.key || deploymentType;
  return (
    <article className="card template-card !flex flex-col gap-3">
      <div className="template-card-head">
        <div className="template-title">
          <span className="runtime-mark">
            <RuntimeIcon type={deploymentType} />
          </span>
          <div className="min-w-0">
            <strong className="block truncate">{name}</strong>
            <div className="muted text-[var(--text-xs)]">{deploymentType}</div>
          </div>
        </div>
      </div>
      <p className="muted m-0 flex-1">{template.description || t("labs.template_default_description")}</p>
      {technical || template.tags?.length ? (
        <div className="template-meta">
          {technical && template.default_image ? (
            <span className="badge truncate-cell" title={template.default_image}>
              {template.default_image}
            </span>
          ) : null}
          {technical && template.default_port ? (
            <span className="badge">{t("labs.template_port", { port: String(template.default_port) })}</span>
          ) : null}
          {(template.tags || []).map((tag) => (
            <span className="badge" key={tag}>
              {tag}
            </span>
          ))}
        </div>
      ) : null}
      <div className="actions-row mt-auto">
        <Button className="w-full" onClick={() => onSelect(template)} aria-label={t("labs.launch_named", { name })}>
          <Rocket size={15} aria-hidden="true" />
          {t("labs.launch")}
        </Button>
      </div>
    </article>
  );
}
