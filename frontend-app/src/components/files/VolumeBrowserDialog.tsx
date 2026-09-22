import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUp,
  Download,
  Eye,
  EyeOff,
  File as FileIcon,
  FileImage,
  FileText,
  Folder,
  FolderPlus,
  Link2,
  Pencil,
  RefreshCw,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createVolumeDirectory,
  deleteVolumeEntry,
  fetchVolumePreviewText,
  listVolumeFiles,
  renameVolumeEntry,
  uploadVolumeFile,
  volumeDownloadUrl,
  volumePreviewUrl,
} from "../../lib/api";
import { dateTime, fileSize } from "../../lib/format";
import { useI18n } from "../../lib/i18n";
import type { VolumeFileEntry, VolumeTarget } from "../../types/api";
import { Button, ErrorState, IconButton, SkeletonRows, TooltipWrapper, cn, showToast } from "../ui";

const LISTING_KEY = "volume-files";

function entryIcon(entry: VolumeFileEntry) {
  if (entry.type === "dir") return <Folder size={16} />;
  if (entry.type === "link") return <Link2 size={16} />;
  if (entry.preview === "image") return <FileImage size={16} />;
  if (entry.preview === "text") return <FileText size={16} />;
  return <FileIcon size={16} />;
}

function entryTypeLabel(
  entry: VolumeFileEntry,
  locale: "fr" | "en",
  t: (key: string, replacements?: Record<string, string | number>) => string,
) {
  if (entry.type === "dir") return t("files.folder");
  if (entry.type === "link") return t("files.link");
  return locale === "fr" ? "Fichier" : "File";
}

function buildCrumbs(root: string, path: string) {
  const crumbs = [{ label: root, path: root }];
  if (!root || !path.startsWith(root)) return crumbs;
  let current = root;
  for (const segment of path.slice(root.length).split("/").filter(Boolean)) {
    current = `${current}/${segment}`;
    crumbs.push({ label: segment, path: current });
  }
  return crumbs;
}

function triggerDownload(url: string) {
  const link = document.createElement("a");
  link.href = url;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function VolumeBrowserDialog({
  target,
  title,
  onClose,
}: {
  target: VolumeTarget;
  title: string;
  onClose: () => void;
}) {
  const { t, locale } = useI18n();
  const queryClient = useQueryClient();

  const [path, setPath] = useState<string | null>(null);
  const [selected, setSelected] = useState<VolumeFileEntry | null>(null);
  const [includeHidden, setIncludeHidden] = useState(false);
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  const [newFolder, setNewFolder] = useState<string | null>(null);
  const [overwrite, setOverwrite] = useState<{ files: File[]; names: string[] } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<VolumeFileEntry | null>(null);
  const [upload, setUpload] = useState<{ done: number; total: number; name: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

  const listing = useQuery({
    queryKey: [LISTING_KEY, target.namespace, target.pod || target.pvc, path, includeHidden],
    queryFn: () => listVolumeFiles(target, path ?? undefined, includeHidden),
    staleTime: 5_000,
  });

  const currentPath = listing.data?.path ?? "";
  const root = listing.data?.root ?? "";
  const entries = listing.data?.entries ?? [];
  const crumbs = useMemo(() => buildCrumbs(root, currentPath), [root, currentPath]);

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: [LISTING_KEY] }),
    [queryClient],
  );

  const navigate = useCallback((next: string) => {
    setPath(next);
    setSelected(null);
    setRenamingPath(null);
    setNewFolder(null);
    setConfirmDelete(null);
  }, []);

  // Un fichier supprimé/renommé ailleurs ne doit pas rester dans le panneau.
  useEffect(() => {
    if (selected && !entries.some((entry) => entry.path === selected.path)) {
      setSelected(null);
    }
  }, [entries, selected]);

  // Un dépôt hors de la zone (ou un drag annulé) ne doit pas laisser
  // l'overlay affiché.
  useEffect(() => {
    if (!dragging) return;
    const reset = () => {
      dragDepth.current = 0;
      setDragging(false);
    };
    window.addEventListener("dragend", reset);
    window.addEventListener("drop", reset);
    return () => {
      window.removeEventListener("dragend", reset);
      window.removeEventListener("drop", reset);
    };
  }, [dragging]);

  const preview = useQuery({
    queryKey: ["volume-preview", selected?.path],
    queryFn: () => fetchVolumePreviewText(target, selected!.path),
    enabled: Boolean(selected && selected.preview === "text"),
    staleTime: 30_000,
  });

  const runUpload = useCallback(
    async (files: File[]) => {
      if (!currentPath || files.length === 0) return;
      let uploaded = 0;
      for (let index = 0; index < files.length; index += 1) {
        setUpload({ done: index, total: files.length, name: files[index].name });
        try {
          await uploadVolumeFile(target, currentPath, files[index]);
          uploaded += 1;
        } catch (error) {
          showToast((error as Error).message, "error");
          break;
        }
      }
      setUpload(null);
      setOverwrite(null);
      if (uploaded > 0) {
        showToast(t("files.uploaded", { count: uploaded }), "success");
        await refresh();
      }
    },
    [currentPath, refresh, t, target],
  );

  const submitFiles = useCallback(
    (files: FileList | File[] | null) => {
      const list = Array.from(files || []);
      if (list.length === 0) return;
      const existing = new Set(entries.map((entry) => entry.name));
      const collisions = list.filter((file) => existing.has(file.name));
      if (collisions.length > 0) {
        setOverwrite({ files: list, names: collisions.map((file) => file.name) });
        return;
      }
      void runUpload(list);
    },
    [entries, runUpload],
  );

  const commitRename = useCallback(
    async (entry: VolumeFileEntry, value: string) => {
      setRenamingPath(null);
      const name = value.trim();
      if (!name || name === entry.name) return;
      try {
        await renameVolumeEntry(target, entry.path, name);
        showToast(t("files.renamed"), "success");
        await refresh();
      } catch (error) {
        showToast((error as Error).message, "error");
      }
    },
    [refresh, t, target],
  );

  const commitNewFolder = useCallback(
    async (value: string) => {
      setNewFolder(null);
      const name = value.trim();
      if (!name || !currentPath) return;
      try {
        await createVolumeDirectory(target, currentPath, name);
        showToast(t("files.folder_created"), "success");
        await refresh();
      } catch (error) {
        showToast((error as Error).message, "error");
      }
    },
    [currentPath, refresh, t, target],
  );

  const removeEntry = useCallback(
    async (entry: VolumeFileEntry) => {
      setConfirmDelete(null);
      try {
        await deleteVolumeEntry(target, entry.path);
        showToast(t("files.deleted"), "success");
        await refresh();
      } catch (error) {
        showToast((error as Error).message, "error");
      }
    },
    [refresh, t, target],
  );

  const openEntry = useCallback((entry: VolumeFileEntry) => {
    if (entry.type === "dir") {
      setPath(entry.path);
      setSelected(null);
      setRenamingPath(null);
      setNewFolder(null);
      setConfirmDelete(null);
    } else {
      setSelected(entry);
    }
  }, []);

  const canBrowse = Boolean(target.pod || target.pvc);

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel volume-browser" aria-describedby={undefined}>
          <div className="vb-head">
            <div className="min-w-0">
              <Dialog.Title asChild>
                <h2 className="truncate">{title}</h2>
              </Dialog.Title>
              <p className="muted code-text truncate">{root || t("files.title")}</p>
            </div>
            <Dialog.Close asChild>
              <IconButton aria-label={t("common.close")}>
                <X size={17} />
              </IconButton>
            </Dialog.Close>
          </div>

          {canBrowse ? (
            <>
              <div className="vb-path">
                <IconButton
                  onClick={() => listing.data?.parent && navigate(listing.data.parent)}
                  disabled={!listing.data?.parent}
                  aria-label={t("files.parent")}
                >
                  <ArrowUp size={15} />
                </IconButton>
                <nav className="vb-crumbs" aria-label={t("files.path")}>
                  {crumbs.map((crumb, index) => (
                    <span className="vb-crumb" key={crumb.path}>
                      {index > 0 ? <span aria-hidden="true">/</span> : null}
                      <button
                        type="button"
                        className={cn(index === crumbs.length - 1 && "current")}
                        onClick={() => navigate(crumb.path)}
                        disabled={index === crumbs.length - 1}
                      >
                        {crumb.label}
                      </button>
                    </span>
                  ))}
                </nav>
                <span className="vb-count">
                  {t("files.count", { count: entries.length })}
                </span>
                <TooltipWrapper content={t("files.hidden")}>
                  <IconButton
                    aria-pressed={includeHidden}
                    aria-label={t("files.hidden")}
                    onClick={() => setIncludeHidden((value) => !value)}
                  >
                    {includeHidden ? <Eye size={15} /> : <EyeOff size={15} />}
                  </IconButton>
                </TooltipWrapper>
                <TooltipWrapper content={t("files.refresh")}>
                  <IconButton onClick={() => void refresh()} disabled={listing.isFetching} aria-label={t("files.refresh")}>
                    <RefreshCw size={15} className={listing.isFetching ? "animate-spin" : undefined} />
                  </IconButton>
                </TooltipWrapper>
              </div>

              <div className="vb-toolbar">
                <Button variant="primary" onClick={() => fileInput.current?.click()} disabled={Boolean(upload)}>
                  <Upload size={15} />
                  {t("files.upload")}
                </Button>
                <Button onClick={() => { setNewFolder(""); setSelected(null); }} disabled={Boolean(upload)}>
                  <FolderPlus size={15} />
                  {t("files.new_folder")}
                </Button>
                <Button
                  onClick={() => currentPath && triggerDownload(volumeDownloadUrl(target, currentPath))}
                  disabled={!currentPath || Boolean(upload)}
                >
                  <Download size={15} />
                  {t("files.download_folder")}
                </Button>
                <input
                  ref={fileInput}
                  type="file"
                  multiple
                  hidden
                  onChange={(event) => {
                    submitFiles(event.target.files);
                    event.target.value = "";
                  }}
                />
              </div>

              {overwrite ? (
                <div className="vb-notice">
                  <AlertTriangle size={16} />
                  <span>
                    {t("files.overwrite_question", { names: overwrite.names.slice(0, 3).join(", ") })}
                    {overwrite.names.length > 3 ? ` (+${overwrite.names.length - 3})` : ""}
                  </span>
                  <Button variant="danger" onClick={() => void runUpload(overwrite.files)}>
                    {t("files.replace")}
                  </Button>
                  <Button onClick={() => setOverwrite(null)}>{t("common.cancel")}</Button>
                </div>
              ) : null}

              {upload ? (
                <div className="vb-notice" role="status">
                  <span className="truncate">
                    {t("files.uploading", { name: upload.name, done: upload.done + 1, total: upload.total })}
                  </span>
                  <div className="meter-track">
                    <div className="meter-fill" style={{ width: `${(upload.done / upload.total) * 100}%` }} />
                  </div>
                </div>
              ) : null}

              <div className="vb-body">
                <div className="vb-list-wrap">
                  <div
                    className="vb-list"
                    onDragEnter={(event) => {
                      event.preventDefault();
                      dragDepth.current += 1;
                      setDragging(true);
                    }}
                    onDragOver={(event) => event.preventDefault()}
                    onDragLeave={() => {
                      dragDepth.current -= 1;
                      if (dragDepth.current <= 0) setDragging(false);
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      dragDepth.current = 0;
                      setDragging(false);
                      submitFiles(event.dataTransfer.files);
                    }}
                  >
                    {listing.isLoading ? (
                      <div className="p-4">
                        <SkeletonRows rows={6} cols={3} />
                      </div>
                    ) : null}

                    {listing.error ? (
                      <div className="p-4">
                        <ErrorState title={t("files.unavailable")}>{(listing.error as Error).message}</ErrorState>
                      </div>
                    ) : null}

                    {listing.data && entries.length === 0 && newFolder === null ? (
                      <div className="empty-state vb-empty">
                        <strong>{t("files.empty_title")}</strong>
                        <span>{t("files.empty_hint")}</span>
                      </div>
                    ) : null}

                    {listing.data && (entries.length > 0 || newFolder !== null) ? (
                      <table className="data-table vb-table">
                        <thead>
                          <tr>
                            <th>{t("files.name")}</th>
                            <th className="vb-right">{t("files.size")}</th>
                            <th className="vb-right">{t("files.modified")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {newFolder !== null ? (
                            <tr className="vb-row">
                              <td colSpan={3}>
                                <InlineInput
                                  icon={<Folder size={16} />}
                                  placeholder={t("files.folder_name")}
                                  initialValue=""
                                  onSubmit={(value) => void commitNewFolder(value)}
                                  onCancel={() => setNewFolder(null)}
                                />
                              </td>
                            </tr>
                          ) : null}
                          {entries.map((entry) => (
                            <tr
                              key={entry.path}
                              className="vb-row"
                              data-selected={selected?.path === entry.path}
                              tabIndex={0}
                              onClick={() => setSelected(entry)}
                              onDoubleClick={() => openEntry(entry)}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.preventDefault();
                                  openEntry(entry);
                                } else if (event.key === " ") {
                                  event.preventDefault();
                                  setSelected(entry);
                                }
                              }}
                            >
                              <td>
                                {renamingPath === entry.path ? (
                                  <InlineInput
                                    icon={entryIcon(entry)}
                                    placeholder={entry.name}
                                    initialValue={entry.name}
                                    onSubmit={(value) => void commitRename(entry, value)}
                                    onCancel={() => setRenamingPath(null)}
                                  />
                                ) : (
                                  <button
                                    type="button"
                                    tabIndex={-1}
                                    className={cn("vb-name", entry.type === "dir" && "dir")}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      setSelected(entry);
                                      if (entry.type === "dir") openEntry(entry);
                                    }}
                                  >
                                    {entryIcon(entry)}
                                    <span className="truncate">{entry.name}</span>
                                  </button>
                                )}
                              </td>
                              <td className="vb-right vb-meta">
                                {entry.type === "dir" ? "—" : fileSize(entry.size, locale)}
                              </td>
                              <td className="vb-right vb-meta">{dateTime(entry.modified_at, locale)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : null}
                  </div>

                  {dragging ? (
                    <div className="vb-drop">
                      <Upload size={22} />
                      <strong>{t("files.drop_hint")}</strong>
                      <span>{currentPath}</span>
                    </div>
                  ) : null}
                </div>

                <aside className="vb-preview">
                  {selected ? (
                    <>
                      <div className="vb-preview-head">
                        <div className="min-w-0">
                          <strong className="truncate">{selected.name}</strong>
                          <span className="muted">
                            {entryTypeLabel(selected, locale, t)}
                            {selected.type === "file" ? ` · ${fileSize(selected.size, locale)}` : ""}
                          </span>
                        </div>
                        <div className="vb-preview-actions">
                          <TooltipWrapper content={t("files.download")}>
                            <IconButton
                              aria-label={t("files.download")}
                              onClick={() => triggerDownload(volumeDownloadUrl(target, selected.path))}
                            >
                              <Download size={15} />
                            </IconButton>
                          </TooltipWrapper>
                          <TooltipWrapper content={t("files.rename")}>
                            <IconButton
                              aria-label={t("files.rename")}
                              onClick={() => setRenamingPath(selected.path)}
                            >
                              <Pencil size={15} />
                            </IconButton>
                          </TooltipWrapper>
                          <TooltipWrapper content={t("files.delete")}>
                            <IconButton
                              aria-label={t("files.delete")}
                              onClick={() => setConfirmDelete(selected)}
                            >
                              <Trash2 size={15} />
                            </IconButton>
                          </TooltipWrapper>
                        </div>
                      </div>

                      {confirmDelete?.path === selected.path ? (
                        <div className="vb-notice inline">
                          <AlertTriangle size={16} />
                          <span>{t("files.delete_question", { name: selected.name })}</span>
                          <Button variant="danger" onClick={() => void removeEntry(selected)}>
                            {t("files.delete")}
                          </Button>
                          <Button onClick={() => setConfirmDelete(null)}>{t("common.cancel")}</Button>
                        </div>
                      ) : null}

                      <div className="vb-preview-body">
                        {selected.type === "dir" ? (
                          <>
                            <p className="muted">{t("files.folder_hint")}</p>
                            <Button
                              variant="primary"
                              onClick={() => triggerDownload(volumeDownloadUrl(target, selected.path))}
                            >
                              <Download size={15} />
                              {t("files.download_folder")}
                            </Button>
                          </>
                        ) : selected.preview === "image" ? (
                          <img
                            className="vb-preview-image"
                            src={volumePreviewUrl(target, selected.path)}
                            alt={selected.name}
                          />
                        ) : selected.preview === "text" ? (
                          preview.isLoading ? (
                            <p className="muted">{t("files.loading_preview")}</p>
                          ) : preview.error ? (
                            <p className="muted">{(preview.error as Error).message}</p>
                          ) : (
                            <>
                              {preview.data?.truncated ? (
                                <p className="vb-truncated">{t("files.preview_truncated")}</p>
                              ) : null}
                              <pre className="vb-preview-text">{preview.data?.text}</pre>
                            </>
                          )
                        ) : (
                          <p className="muted">{t("files.preview_unavailable")}</p>
                        )}
                      </div>
                    </>
                  ) : (
                    <div className="vb-preview-empty">
                      <FileIcon size={20} />
                      <p className="muted">{t("files.select_hint")}</p>
                    </div>
                  )}
                </aside>
              </div>
            </>
          ) : (
            <div className="p-4">
              <ErrorState title={t("files.unavailable")}>{t("files.no_target")}</ErrorState>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function InlineInput({
  icon,
  placeholder,
  initialValue,
  onSubmit,
  onCancel,
}: {
  icon: ReactNode;
  placeholder: string;
  initialValue: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initialValue);
  return (
    <span className="vb-inline-input">
      {icon}
      <input
        autoFocus
        value={value}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(event) => setValue(event.target.value)}
        onBlur={onCancel}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            onSubmit(value);
          }
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          }
        }}
      />
    </span>
  );
}
