import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit2, Plus, Sliders, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useDebounce } from "../../hooks";
import { deleteUser, getSsoStatus, getUsers } from "../../lib/api";
import { authProviderLabel, roleLabel, shortDate } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { User } from "../../types/api";
import { Button, ConfirmDialog, EmptyState, errorMessage, Pagination, QueryState, SearchBox, showToast, SkeletonRows, StatusBadge } from "../ui";
import { type ColumnDef, DataTable } from "../DataTable";
import { CsvImportDialog } from "./CsvImportDialog";
import { QuotaDialog } from "./QuotaDialog";
import { UserDialog } from "./UserDialog";

const PAGE_SIZES = [10, 25, 50, 100];

/** Users list (server-side filters and pagination) with create / edit / quotas / delete / CSV import. */
export function UsersTab() {
  const { locale, t } = useI18n();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [authProvider, setAuthProvider] = useState("");
  const [page, setPage] = useState(1);
  const [limit, setLimit] = useState(25);
  const [userDialog, setUserDialog] = useState<{ open: boolean; user: User | null }>({ open: false, user: null });
  const [quotaUser, setQuotaUser] = useState<User | null>(null);
  const [showCsvImport, setShowCsvImport] = useState(false);
  const debouncedSearch = useDebounce(search, 300);

  const sso = useQuery({ queryKey: ["sso-status"], queryFn: getSsoStatus });
  const users = useQuery({
    queryKey: ["users", { search: debouncedSearch, role, auth_provider: authProvider, userPage: page, userLimit: limit }],
    queryFn: () =>
      getUsers({
        search: debouncedSearch || undefined,
        role: (role as "admin" | "teacher" | "student") || undefined,
        auth_provider: authProvider || undefined,
        skip: (page - 1) * limit,
        limit,
      }),
    placeholderData: keepPreviousData,
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, role, authProvider, limit]);

  const deleteUserMut = useMutation({
    mutationFn: (userId: number) => deleteUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      showToast(t("admin.toast_user_deleted"), "success");
    },
    onError: (error) => showToast(errorMessage(error, t("admin.error_delete_user")), "error"),
  });

  const columns = useMemo<ColumnDef<User>[]>(
    () => [
      { id: "id", header: "ID", accessorFn: (u) => u.id, enableSorting: false },
      { id: "name", header: t("admin.col_name"), accessorFn: (u) => u.full_name || u.username, enableSorting: false },
      {
        id: "email",
        header: t("students.email"),
        enableSorting: false,
        cell: ({ row }) => row.original.email || <span className="muted">—</span>,
      },
      {
        id: "auth",
        header: t("admin.col_auth"),
        enableSorting: false,
        cell: ({ row }) => <span className="badge">{authProviderLabel(row.original.auth_provider)}</span>,
      },
      {
        id: "role",
        header: t("admin.col_role"),
        enableSorting: false,
        cell: ({ row }) => <span className="badge">{roleLabel(row.original.role, locale)}</span>,
      },
      {
        id: "status",
        header: t("submission.status"),
        enableSorting: false,
        cell: ({ row }) => <StatusBadge state={row.original.is_active ? "active" : "inactive"} />,
      },
      {
        id: "created",
        header: t("admin.col_created_at"),
        enableSorting: false,
        cell: ({ row }) => shortDate(row.original.created_at),
      },
      {
        id: "actions",
        header: t("students.actions"),
        enableSorting: false,
        cell: ({ row }) => {
          const user = row.original;
          return (
            <div className="actions-row gap-1">
              <Button
                onClick={() => setUserDialog({ open: true, user })}
                title={t("admin.edit_user")}
                aria-label={t("admin.edit_user_named", { name: user.username })}
              >
                <Edit2 size={14} aria-hidden="true" />
              </Button>
              <Button
                onClick={() => setQuotaUser(user)}
                title={t("admin.user_quotas")}
                aria-label={t("admin.user_quotas_named", { name: user.username })}
              >
                <Sliders size={14} aria-hidden="true" />
              </Button>
              <ConfirmDialog
                destructive
                title={t("admin.delete_user")}
                description={t("admin.delete_user_body", { name: user.username })}
                confirmLabel={t("common.delete")}
                trigger={
                  <Button
                    variant="danger"
                    disabled={deleteUserMut.isPending && deleteUserMut.variables === user.id}
                    title={t("admin.delete_user")}
                    aria-label={t("admin.delete_user_named", { name: user.username })}
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </Button>
                }
                onConfirm={() => deleteUserMut.mutate(user.id)}
              />
            </div>
          );
        },
      },
    ],
    [deleteUserMut, locale, t],
  );

  const items = users.data || [];
  const totalPages = items.length >= limit ? page + 1 : page;
  const filtered = Boolean(debouncedSearch || role || authProvider);

  return (
    <section className="panel">
      <div className="section-head">
        <h2>
          {t("admin.users_title")}
          {users.data ? ` (${items.length})` : ""}
        </h2>
        <div className="actions-row">
          <Button variant="primary" onClick={() => setUserDialog({ open: true, user: null })}>
            <Plus size={16} aria-hidden="true" /> {t("admin.new_user")}
          </Button>
          <Button onClick={() => setShowCsvImport(true)}>
            <Upload size={16} aria-hidden="true" /> {t("admin.import_csv")}
          </Button>
        </div>
      </div>
      <div className="actions-row mb-3 gap-2.5">
        <SearchBox placeholder={t("common.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="control" value={role} onChange={(e) => setRole(e.target.value)} aria-label={t("admin.filter_role")}>
          <option value="">{t("admin.all_roles")}</option>
          <option value="student">{roleLabel("student", locale)}</option>
          <option value="teacher">{roleLabel("teacher", locale)}</option>
          <option value="admin">{roleLabel("admin", locale)}</option>
        </select>
        <select
          className="control"
          value={authProvider}
          onChange={(e) => setAuthProvider(e.target.value)}
          aria-label={t("admin.filter_provider")}
        >
          <option value="">{t("admin.all_providers")}</option>
          <option value="local">{authProviderLabel("local")}</option>
          <option value="oidc">{authProviderLabel("oidc")}</option>
        </select>
        <select
          className="control"
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          aria-label={t("admin.page_size")}
        >
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>
              {t("admin.per_page", { count: size })}
            </option>
          ))}
        </select>
      </div>
      <QueryState
        query={users}
        skeleton={<SkeletonRows rows={8} cols={6} />}
        errorTitle={t("admin.error_users")}
        isEmpty={items.length === 0}
        empty={
          filtered ? (
            <EmptyState title={t("admin.users_no_match")}>{t("admin.filters_no_match_hint")}</EmptyState>
          ) : (
            <EmptyState title={t("admin.users_empty")} />
          )
        }
      >
        <DataTable data={items} columns={columns} getRowId={(u) => String(u.id)} label={t("admin.users_title")} />
      </QueryState>
      <Pagination page={page} totalPages={totalPages} onChange={setPage} />

      {/* Mounted only while open: each opening starts from the item's current values. */}
      {userDialog.open ? (
        <UserDialog
          key={userDialog.user?.id ?? "new"}
          user={userDialog.user}
          ssoEnabled={Boolean(sso.data)}
          open
          onOpenChange={(open) => setUserDialog((prev) => ({ ...prev, open }))}
        />
      ) : null}
      {quotaUser ? (
        <QuotaDialog
          key={quotaUser.id}
          user={quotaUser}
          open
          onOpenChange={(o) => {
            if (!o) setQuotaUser(null);
          }}
        />
      ) : null}
      <CsvImportDialog open={showCsvImport} onOpenChange={setShowCsvImport} />
    </section>
  );
}
