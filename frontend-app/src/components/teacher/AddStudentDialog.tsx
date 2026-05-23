import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Upload, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { User } from "../../types/api";
import { enrollStudents, importStudentsCsv, searchStudents } from "../../lib/api";
import { Button, ErrorState, IconButton, LoadingState, showToast } from "../ui";

interface AddStudentDialogProps {
  classroomId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddStudentDialog({ classroomId, open, onOpenChange }: AddStudentDialogProps) {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<User[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<"search" | "csv">("search");
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const enrollMutation = useMutation({
    mutationFn: (userIds: number[]) => enrollStudents(classroomId, userIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classroom-students", classroomId] });
      showToast("Etudiants inscrits", "success");
      onOpenChange(false);
      reset();
    },
  });

  const csvMutation = useMutation({
    mutationFn: (file: File) => importStudentsCsv(classroomId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classroom-students", classroomId] });
      showToast("Etudiants importes", "success");
      onOpenChange(false);
      reset();
    },
  });

  const reset = () => {
    setQuery("");
    setResults([]);
    setSelected(new Set());
    setMode("search");
    setCsvFile(null);
  };

  const doSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const data = await searchStudents(query);
      setResults(data || []);
    } catch {
      showToast("Erreur de recherche", "error");
    }
    setSearching(false);
  };

  const toggleUser = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) reset(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content panel">
          <div className="section-head">
            <Dialog.Title asChild>
              <h2>Ajouter des etudiants</h2>
            </Dialog.Title>
            <Dialog.Close asChild>
              <IconButton aria-label="Fermer"><X size={17} /></IconButton>
            </Dialog.Close>
          </div>

          <div className="actions-row" style={{ marginBottom: 14 }}>
            <Button variant={mode === "search" ? "primary" : "default"} onClick={() => setMode("search")}>
              <Search size={16} /> Rechercher
            </Button>
            <Button variant={mode === "csv" ? "primary" : "default"} onClick={() => setMode("csv")}>
              <Upload size={16} /> CSV
            </Button>
          </div>

          {mode === "search" ? (
            <div style={{ display: "grid", gap: 14 }}>
              <div className="actions-row">
                <input
                  placeholder="Rechercher par nom ou email..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && doSearch()}
                  style={{ flex: 1, minHeight: 38, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8 }}
                />
                <Button variant="primary" onClick={doSearch}><Search size={16} /></Button>
              </div>
              {searching ? <LoadingState label="Recherche..." /> : null}
              {results.length > 0 ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th></th>
                        <th>Nom</th>
                        <th>Email</th>
                        <th>Role</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((user) => (
                        <tr key={user.id}>
                          <td>
                            <input type="checkbox" checked={selected.has(user.id)} onChange={() => toggleUser(user.id)} />
                          </td>
                          <td>{user.full_name || user.username}</td>
                          <td>{user.email || "N/A"}</td>
                          <td>{user.role}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              <div className="actions-row" style={{ justifyContent: "end" }}>
                <Button onClick={() => onOpenChange(false)}>Annuler</Button>
                <Button variant="primary" disabled={selected.size === 0 || enrollMutation.isPending} onClick={() => enrollMutation.mutate([...selected])}>
                  {enrollMutation.isPending ? "Inscription..." : `Inscrire ${selected.size} etudiant(s)`}
                </Button>
              </div>
            </div>
          ) : (
            <div style={{ display: "grid", gap: 14 }}>
              <div className="field full">
                <label htmlFor="student-csv">Fichier CSV (format: username,email,full_name)</label>
                <input id="student-csv" type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] || null)} />
              </div>
              {csvMutation.error ? <ErrorState>{csvMutation.error.message}</ErrorState> : null}
              <div className="actions-row" style={{ justifyContent: "end" }}>
                <Button onClick={() => setMode("search")}>Retour</Button>
                <Button variant="primary" disabled={!csvFile || csvMutation.isPending} onClick={() => csvFile && csvMutation.mutate(csvFile)}>
                  {csvMutation.isPending ? "Import..." : "Importer CSV"}
                </Button>
              </div>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
