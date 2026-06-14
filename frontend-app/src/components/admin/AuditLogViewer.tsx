import { useQuery } from "@tanstack/react-query";
import { Activity, Download, Eye, Gauge, Layers, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { AuditLogEntry } from "../../types/api";
import { exportAuditLogs, getAuditLogs, getAuditLogStats } from "../../lib/api";
import { fullDate } from "../../lib/format";
import { Button, EmptyState, ErrorState, MetricCard, Pagination, SearchBox, SkeletonRows, showToast } from "../ui";

export function AuditLogViewer() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [event, setEvent] = useState("");
  const [category, setCategory] = useState("");
  const [level, setLevel] = useState("");
  const [username, setUsername] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [pageSize, setPageSize] = useState(50);
  const [selectedEntry, setSelectedEntry] = useState<AuditLogEntry | null>(null);

  const stats = useQuery({
    queryKey: ["audit-stats"],
    queryFn: getAuditLogStats,
    staleTime: 60_000,
  });

  const logs = useQuery({
    queryKey: ["audit-logs", { page, pageSize, search, event, category, level, username, dateFrom, dateTo }],
    queryFn: () =>
      getAuditLogs({
        page,
        page_size: pageSize,
        search: search || undefined,
        event: event || undefined,
        category: category || undefined,
        level: level || undefined,
        username: username || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      }),
  });

  const totalPages = logs.data?.total ? Math.ceil(logs.data.total / pageSize) : 1;

  const handleExport = async () => {
    try {
      const data = await exportAuditLogs({
        search: search || undefined,
        event: event || undefined,
        category: category || undefined,
        level: level || undefined,
        username: username || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit-logs-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showToast("Export termine", "success");
    } catch {
      showToast("Erreur d'export", "error");
    }
  };

  const levelBadge = (l?: string) => {
    if (l === "ERROR" || l === "error") return <span className="badge red">{l}</span>;
    if (l === "WARNING" || l === "warning") return <span className="badge amber">{l}</span>;
    if (l === "INFO" || l === "info") return <span className="badge blue">{l}</span>;
    return <span className="badge">{l}</span>;
  };

  return (
    <div className="grid gap-5">
      {stats.data ? (
        <section className="metric-grid">
          <MetricCard label="Total" value={stats.data.total || 0} icon={<Eye size={18} />} hint="Événements enregistrés" />
          <MetricCard
            label="Catégories"
            value={Object.keys(stats.data.by_category || {}).length}
            icon={<Layers size={18} />}
            hint="Types distincts"
          />
          <MetricCard
            label="Niveaux"
            value={Object.keys(stats.data.by_level || {}).length}
            icon={<Gauge size={18} />}
            hint="Sévérités"
          />
          <MetricCard
            label="7 derniers jours"
            value={stats.data.last_7_days ? Object.values(stats.data.last_7_days).reduce((a, b) => a + b, 0) : 0}
            icon={<Activity size={18} />}
            hint="Activité récente"
          />
        </section>
      ) : null}

      {stats.data?.last_7_days ? (
        <section className="panel">
          <div className="section-head">
            <h2>Activité 7 jours</h2>
            <span className="badge blue">{Object.values(stats.data.last_7_days).reduce((a, b) => a + b, 0)} évts</span>
          </div>
          <div className="grid grid-cols-7 items-end gap-2.5">
            {Object.entries(stats.data.last_7_days).map(([day, count]) => {
              const max = Math.max(...Object.values(stats.data!.last_7_days || { x: 1 }));
              const pct = Math.max(6, (count / Math.max(max, 1)) * 100);
              return (
                <div className="group grid gap-2 text-center" key={day} title={`${day}: ${count}`}>
                  <span
                    className="text-[0.78rem] font-bold leading-none text-[var(--text-soft)]"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {count}
                  </span>
                  <div className="meter-track flex h-[96px] items-end rounded-[10px]">
                    <div
                      className="meter-fill w-full rounded-[10px] transition-[height] duration-500"
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
          <h2>Filtres</h2>
          <Button onClick={handleExport}><Download size={16} /> Export JSON</Button>
        </div>
        <div className="actions-row mb-3.5 gap-2.5">
          <SearchBox placeholder="Recherche texte..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
          <input
            placeholder="Evenement"
            value={event}
            onChange={(e) => { setEvent(e.target.value); setPage(1); }}
            className="control control-wide"
          />
          <input
            placeholder="Categorie"
            value={category}
            onChange={(e) => { setCategory(e.target.value); setPage(1); }}
            className="control control-narrow"
          />
          <select className="control" value={level} onChange={(e) => { setLevel(e.target.value); setPage(1); }}>
            <option value="">Tous niveaux</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
          <input
            placeholder="Utilisateur"
            value={username}
            onChange={(e) => { setUsername(e.target.value); setPage(1); }}
            className="control control-narrow"
          />
          <input className="control" type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} />
          <input className="control" type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} />
          <select className="control" value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>
          <Button onClick={() => { setSearch(""); setEvent(""); setCategory(""); setLevel(""); setUsername(""); setDateFrom(""); setDateTo(""); setPage(1); }}>
            <RefreshCw size={16} />
            <span>Réinitialiser</span>
          </Button>
        </div>

        {logs.isLoading ? <SkeletonRows rows={8} cols={5} /> : null}
        {logs.error ? <ErrorState>Impossible de charger les logs.</ErrorState> : null}

        {(logs.data?.items || []).length ? (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Niveau</th>
                    <th>Evenement</th>
                    <th>Categorie</th>
                    <th>Utilisateur</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {(logs.data?.items || []).map((entry, i) => (
                    <tr key={entry.id || i}>
                      <td>{fullDate(entry.timestamp)}</td>
                      <td>{levelBadge(entry.level)}</td>
                      <td>{entry.event_label || entry.event || entry.message || "N/A"}</td>
                      <td>{entry.category || "N/A"}</td>
                      <td>{entry.username || "N/A"}</td>
                      <td>
                        <Button onClick={() => setSelectedEntry(entry)}>
                          <Eye size={14} />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} totalPages={totalPages} onChange={setPage} />
          </>
        ) : !logs.isLoading && !logs.error ? (
          <EmptyState title="Aucun log">{search || event || category || level || username || dateFrom || dateTo ? "Aucun événement ne correspond aux filtres." : "Aucun événement d'audit disponible."}</EmptyState>
        ) : null}
      </section>

      {selectedEntry ? (
        <section className="panel">
          <div className="section-head">
            <h2>Detail: {selectedEntry.event_label || selectedEntry.event || selectedEntry.message || "audit"}</h2>
            <Button onClick={() => setSelectedEntry(null)}>Fermer</Button>
          </div>
          <pre className="pre-wrap">
            {JSON.stringify(selectedEntry, null, 2)}
          </pre>
        </section>
      ) : null}
    </div>
  );
}
