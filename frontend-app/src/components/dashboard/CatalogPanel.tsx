import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { getTemplates } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import type { Template } from "../../types/api";
import { TemplateCard } from "../TemplateCard";
import { Button, EmptyState, SearchBox, SkeletonCards } from "../ui";
import { QueryProblem } from "./QueryProblem";

export const CATALOG_ID = "lab-catalog";
export const CATALOG_SEARCH_ID = "lab-catalog-search";

/** Templates the user may launch, with a text filter. */
export function CatalogPanel({ technical, onSelect }: { technical: boolean; onSelect: (template: Template) => void }) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const templates = useQuery({ queryKey: ["templates"], queryFn: getTemplates });

  const filtered = useMemo(() => {
    const text = search.trim().toLowerCase();
    return (templates.data || []).filter((item) => {
      if (!text) return true;
      return `${item.name} ${item.description || ""} ${(item.tags || []).join(" ")}`.toLowerCase().includes(text);
    });
  }, [search, templates.data]);

  return (
    <section className="panel scroll-mt-4" id={CATALOG_ID} aria-labelledby="catalog-title">
      <div className="section-head flex-wrap">
        <div>
          <h2 id="catalog-title">{t("labs.catalog_title")}</h2>
          <p className="muted m-0 text-[var(--text-sm)]">{t("labs.catalog_subtitle")}</p>
        </div>
        <SearchBox
          id={CATALOG_SEARCH_ID}
          type="search"
          placeholder={t("labs.catalog_search")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {templates.isLoading ? <SkeletonCards count={3} lines={2} /> : null}
      {templates.error ? (
        <QueryProblem
          error={templates.error}
          title={t("labs.catalog_error")}
          onRetry={() => void templates.refetch()}
          retrying={templates.isFetching}
          stale={Boolean(templates.data)}
        />
      ) : null}
      {templates.data && filtered.length === 0 ? (
        <EmptyState title={search ? t("labs.catalog_no_match_title") : t("labs.catalog_empty_title")}>
          {search ? (
            <span className="grid justify-items-center gap-3">
              {t("labs.catalog_no_match", { query: search.trim() })}
              <Button onClick={() => setSearch("")}>{t("labs.catalog_clear")}</Button>
            </span>
          ) : (
            t("labs.catalog_empty")
          )}
        </EmptyState>
      ) : null}
      {filtered.length ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((template, index) => (
            <TemplateCard
              key={String(template.key || template.id || template.name)}
              index={index}
              template={template}
              technical={technical}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
