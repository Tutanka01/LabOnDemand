import * as Dialog from "@radix-ui/react-dialog";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Upload, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import type { User } from "../../types/api";
import { createAndEnrollStudent, enrollStudents, importStudentsCsv, searchStudents } from "../../lib/api";
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
  const [mode, setMode] = useState<"search" | "create" | "csv">("search");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [newStudent, setNewStudent] = useState({ username: "", email: "", full_name: "", password: "" });

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

  const createMutation = useMutation({
    mutationFn: () => createAndEnrollStudent(classroomId, newStudent),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classroom-students", classroomId] });
      showToast("Compte etudiant cree et inscrit", "success");
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
    setNewStudent({ username: "", email: "", full_name: "", password: "" });
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

          <div className="actions-row mb-3.5">
            <Button variant={mode === "search" ? "primary" : "default"} onClick={() => setMode("search")}>
              <Search size={16} /> Rechercher
            </Button>
            <Button variant={mode === "create" ? "primary" : "default"} onClick={() => setMode("create")}>
              <UserPlus size={16} /> Creer un compte
            </Button>
            <Button variant={mode === "csv" ? "primary" : "default"} onClick={() => setMode("csv")}>
              <Upload size={16} /> CSV
            </Button>
          </div>

          {mode === "search" ? (
            <div className="grid gap-3.5">
              <div className="actions-row">
                <input
                  className="control flex-1"
                  placeholder="Rechercher par nom ou email..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && doSearch()}
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
              <div className="actions-row justify-end">
                <Button onClick={() => onOpenChange(false)}>Annuler</Button>
                <Button variant="primary" disabled={selected.size === 0 || enrollMutation.isPending} onClick={() => enrollMutation.mutate([...selected])}>
                  {enrollMutation.isPending ? "Inscription..." : `Inscrire ${selected.size} etudiant(s)`}
                </Button>
              </div>
            </div>
          ) : mode === "create" ? (
            <div className="form-grid">
              <div className="field">
                <label htmlFor="new-student-username">Nom d'utilisateur</label>
                <input
                  id="new-student-username"
                  value={newStudent.username}
                  onChange={(e) => setNewStudent((prev) => ({ ...prev, username: e.target.value }))}
                  placeholder="jean.dupont"
                />
              </div>
              <div className="field">
                <label htmlFor="new-student-email">Email</label>
                <input
                  id="new-student-email"
                  type="email"
                  value={newStudent.email}
                  onChange={(e) => setNewStudent((prev) => ({ ...prev, email: e.target.value }))}
                  placeholder="jean.dupont@univ.fr"
                />
              </div>
              <div className="field">
                <label htmlFor="new-student-name">Nom complet</label>
                <input
                  id="new-student-name"
                  value={newStudent.full_name}
                  onChange={(e) => setNewStudent((prev) => ({ ...prev, full_name: e.target.value }))}
                  placeholder="Jean Dupont"
                />
              </div>
              <div className="field">
                <label htmlFor="new-student-password">Mot de passe initial</label>
                <input
                  id="new-student-password"
                  type="password"
                  value={newStudent.password}
                  onChange={(e) => setNewStudent((prev) => ({ ...prev, password: e.target.value }))}
                  placeholder="12 caracteres min."
                />
              </div>
              <p className="muted field full">Le mot de passe doit contenir au moins 12 caracteres, une majuscule, une minuscule, un chiffre et un caractere special.</p>
              {createMutation.error ? <ErrorState>{createMutation.error.message}</ErrorState> : null}
              <div className="actions-row field full justify-end">
                <Button onClick={() => setMode("search")}>Retour</Button>
                <Button
                  variant="primary"
                  disabled={!newStudent.username || !newStudent.email || !newStudent.password || createMutation.isPending}
                  onClick={() => createMutation.mutate()}
                >
                  {createMutation.isPending ? "Creation..." : "Creer et inscrire"}
                </Button>
              </div>
            </div>
          ) : (
            <div className="grid gap-3.5">
              <div className="field full">
                <label htmlFor="student-csv">Fichier CSV (format: username,email,full_name)</label>
                <input id="student-csv" type="file" accept=".csv" onChange={(e) => setCsvFile(e.target.files?.[0] || null)} />
              </div>
              {csvMutation.error ? <ErrorState>{csvMutation.error.message}</ErrorState> : null}
              <div className="actions-row justify-end">
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
