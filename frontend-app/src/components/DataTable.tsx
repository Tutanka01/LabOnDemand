import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useState } from "react";
import { useI18n } from "../lib/i18n";

// Kept out of ../ui.tsx so @tanstack/react-table only loads with the teacher/admin pages,
// not in the shared chunk every page (including the student dashboard) downloads.
export type { ColumnDef, SortingState } from "@tanstack/react-table";


/**
 * Client-side sortable table built on @tanstack/react-table. Columns opt out of sorting
 * with `enableSorting: false` (e.g. action columns).
 */
export function DataTable<T>({
  data,
  columns,
  getRowId,
  initialSorting = [],
  label,
}: {
  data: T[];
  columns: ColumnDef<T>[];
  getRowId?: (row: T, index: number) => string;
  initialSorting?: SortingState;
  label?: string;
}) {
  const { t } = useI18n();
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="table-wrap">
      <table className="data-table" aria-label={label}>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => {
                const sorted = header.column.getIsSorted();
                const content = header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext());
                return (
                  <th
                    key={header.id}
                    aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                  >
                    {header.column.getCanSort() ? (
                      <button
                        type="button"
                        className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-inherit [font:inherit] [letter-spacing:inherit] uppercase"
                        onClick={header.column.getToggleSortingHandler()}
                        title={t("common.sort")}
                      >
                        {content}
                        {sorted === "asc" ? (
                          <ArrowUp size={12} aria-hidden="true" />
                        ) : sorted === "desc" ? (
                          <ArrowDown size={12} aria-hidden="true" />
                        ) : (
                          <ArrowUpDown size={12} className="opacity-40" aria-hidden="true" />
                        )}
                      </button>
                    ) : (
                      content
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
