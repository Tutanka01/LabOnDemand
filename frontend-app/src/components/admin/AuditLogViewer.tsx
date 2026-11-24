import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { Activity, Download, Eye, Gauge, Layers, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useDebounce } from "../../hooks";
import type { AuditLogEntry } from "../../types/api";
import { exportAuditLogs, getAuditLogs, getAuditLogStats } from "../../lib/api";
import { fullDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import {
  Button,
  EmptyState,
  errorMessage,
  MetricCard,
  ModalShell,
  Pagination,
  QueryState,
  SearchBox,
  showToast,
  SkeletonRows,
} from "../ui";

type Filters = {
  search: string;
  event: string;
  category: string;
  level: string;
  username: string;
  dateFrom: string;
  dateTo: string;
};

const EMPTY_FILTERS: Filters = { search: "", event: "", category: "", level: "", username: "", dateFrom: "", dateTo: "" };

const PAGE_SIZES = [25, 50, 100];

function LevelBadge({ level }: { level?: string }) {
  const upper = (level || "").toUpperCase();
  const tone = upper === "ERROR" ? " red" : upper === "WARNING" ? " amber" : upper === "INFO" ? " blue" : "";
  return <span className={`badge${tone}`}>{level}</span>;
}

const entryTitle = (entry: AuditLogEntry) => entry.event_label || entry.event || entry.message || "audit";

/** Audit log: activity summary, filters, paginated table, JSON export and entry details. */
export function AuditLogViewer() {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [selectedEntry, setSelectedEntry] = useState<AuditLogEntry | null>(null);
  // Text inputs are debounced so typing does not fire one request per keystroke.
  const debounced = useDebounce(filters, 300);

  const setFilter = (key: keyof Filters, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
  };

  const apiFilters = {
    search: debounced.search || undefined,
    event: debounced.event || undefined,
    category: debounced.category || undefined,
    level: debounced.level || undefined,
    username: debounced.username || undefined,
    date_from: debounced.dateFrom || undefined,
    date_to: debounced.dateTo || undefined,
  };

  const stats = useQuery({ queryKey: ["audit-stats"], queryFn: getAuditLogStats, staleTime: 60_000 });

  const logs = useQuery({
    queryKey: ["audit-logs", { page, pageSize, ...debounced }],
    queryFn: () => getAuditLogs({ page, page_size: pageSize, ...apiFilters }),
    placeholderData: keepPreviousData,
  });

  const exportMut = useMutation({
    mutationFn: () => exportAuditLogs(apiFilters),
    onSuccess: (data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(t("admin.audit_export_done"), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("admin.audit_export_failed")), "error"),
  });

  const totalPages = logs.data?.total ? Math.ceil(logs.data.total / pageSize) : 1;
  const items = logs.data?.items || [];
  const filtersActive = Object.values(filters).some(Boolean);
  const last7 = stats.data?.last_7_days;
  const last7Total = last7 ? Object.values(last7).reduce((a, b) => a + b, 0) : 0;
  const last7Max = last7 ? Math.max(1, ...Object.values(last7)) : 1;

  return (
    <div className="grid gap-5">
      {stats.data ? (
        <section className="metric-grid">
          <MetricCard label={t("admin.metric_total")} value={stats.data.total || 0} icon={<Eye size={18} />} hint={t("admin.audit_metric_events")} />
          <MetricCard
            label={t("admin.audit_categories")}
            value={Object.keys(stats.data.by_category || {}).length}
            icon={<Layers size={18} />}
            hint={t("admin.audit_metric_types")}
          />
          <MetricCard
            label={t("admin.audit_levels")}
            value={Object.keys(stats.data.by_level || {}).length}
            icon={<Gauge size={18} />}
            hint={t("admin.audit_metric_severities")}
          />
          <MetricCard label={t("admin.audit_last_7_days")} value={last7Total} icon={<Activity size={18} />} hint={t("admin.audit_metric_recent")} />
        </section>
      ) : null}

      {last7 ? (
        <section className="panel">
          <div className="section-head">
            <h2>{t("admin.audit_activity_7d")}</h2>
            <span className="badge blue">{t("admin.audit_events_count", { count: last7Total })}</span>
          </div>
          <div className="grid grid-cols-7 items-end gap-2.5" role="img" aria-label={t("admin.audit_activity_7d")}>
            {Object.entries(last7).map(([day, count]) => {
              const pct = Math.max(6, (count / last7Max) * 100);
              return (
                <div className="group grid gap-2 text-center" key={day} title={`${day}: ${count}`}>
                  <span className="text-xs font-bold leading-none text-[var(--text-soft)]">{count}</span>
                  <div className="meter-track flex h-[96px] items-end rounded-[var(--radius)]">
                    <div
                      className="meter-fill w-full rounded-[var(--radius)] transition-[height] duration-500"
                      style={{ height: `${pct}%` }}
                    />
                  </div>
                  <span className="muted text-xs">{day}</span>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="section-head">
          <h2>{t("admin.audit_filters")}</h2>
          <Button onClick={() => exportMut.mutate()} disabled={exportMut.isPending}>
            <Download size={16} aria-hidden="true" /> {exportMut.isPending ? t("admin.audit_exporting") : t("admin.audit_export")}
          </Button>
        </div>
        <div className="actions-row mb-3.5 gap-2.5">
          <SearchBox placeholder={t("admin.audit_search")} value={filters.search} onChange={(e) => setFilter("search", e.target.value)} />
          <input
            placeholder={t("admin.audit_event")}
            aria-label={t("admin.audit_event")}
            value={filters.event}
            onChange={(e) => setFilter("event", e.target.value)}
            className="control control-wide"
          />
          <input
            placeholder={t("admin.audit_category")}
            aria-label={t("admin.audit_category")}
            value={filters.category}
            onChange={(e) => setFilter("category", e.target.value)}
            className="control control-narrow"
          />
          <select
            className="control"
            value={filters.level}
            onChange={(e) => setFilter("level", e.target.value)}
            aria-label={t("admin.audit_level")}
          >
            <option value="">{t("admin.audit_all_levels")}</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
          <input
            placeholder={t("admin.audit_user")}
            aria-label={t("admin.audit_user")}
            value={filters.username}
            onChange={(e) => setFilter("username", e.target.value)}
            className="control control-narrow"
          />
          <input
            className="control"
            type="date"
            aria-label={t("admin.audit_date_from")}
            title={t("admin.audit_date_from")}
            value={filters.dateFrom}
            onChange={(e) => setFilter("dateFrom", e.target.value)}
          />
          <input
            className="control"
            type="date"
            aria-label={t("admin.audit_date_to")}
            title={t("admin.audit_date_to")}
            value={filters.dateTo}
            onChange={(e) => setFilter("dateTo", e.target.value)}
          />
          <select
            className="control"
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
            aria-label={t("admin.page_size")}
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {t("admin.per_page", { count: size })}
              </option>
            ))}
          </select>
          <Button
            onClick={() => {
              setFilters(EMPTY_FILTERS);
              setPage(1);
            }}
            disabled={!filtersActive}
          >
            <RotateCcw size={16} aria-hidden="true" />
            <span>{t("admin.audit_reset")}</span>
          </Button>
        </div>

        <QueryState
          query={logs}
          skeleton={<SkeletonRows rows={8} cols={5} />}
          errorTitle={t("admin.error_audit")}
          isEmpty={items.length === 0}
          empty={
            <EmptyState title={t("admin.audit_empty")}>
              {filtersActive ? t("admin.audit_no_match") : t("admin.audit_none")}
            </EmptyState>
          }
        >
          <div className="table-wrap">
            <table className="data-table" aria-label={t("admin.tab_audit")}>
              <thead>
                <tr>
                  <th>{t("admin.audit_date")}</th>
                  <th>{t("admin.audit_level")}</th>
                  <th>{t("admin.audit_event")}</th>
                  <th>{t("admin.audit_category")}</th>
                  <th>{t("admin.audit_user")}</th>
                  <th>
                    <span className="sr-only">{t("common.details")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((entry, i) => (
                  <tr key={entry.id || i}>
                    <td>{fullDate(entry.timestamp)}</td>
                    <td>
                      <LevelBadge level={entry.level} />
                    </td>
                    <td>{entry.event_label || entry.event || entry.message || "—"}</td>
                    <td>{entry.category || "—"}</td>
                    <td>{entry.username || "—"}</td>
                    <td>
                      <Button onClick={() => setSelectedEntry(entry)} aria-label={t("admin.audit_view_details")} title={t("common.details")}>
                        <Eye size={14} aria-hidden="true" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} totalPages={totalPages} onChange={setPage} />
        </QueryState>
      </section>

      <ModalShell
        open={selectedEntry !== null}
        onOpenChange={(o) => {
          if (!o) setSelectedEntry(null);
        }}
        title={selectedEntry ? t("admin.audit_detail_title", { title: entryTitle(selectedEntry) }) : ""}
        wide
      >
        {selectedEntry ? <pre className="pre-wrap overflow-x-auto text-xs">{JSON.stringify(selectedEntry, null, 2)}</pre> : null}
      </ModalShell>
    </div>
  );
}
