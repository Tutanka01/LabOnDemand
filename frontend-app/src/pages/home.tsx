import { useOutletContext } from "react-router-dom";
import type { User } from "../types/api";
import DashboardPage from "./dashboard";
import MyAssignmentsPage from "./my-assignments";

/**
 * Page d'accueil `/` : pour un étudiant, la porte d'entrée devient « Mes devoirs ».
 * Les enseignants et admins conservent le tableau de bord des labs.
 */
export default function HomePage() {
  const user = useOutletContext<User>();
  if (user.role === "student") return <MyAssignmentsPage />;
  return <DashboardPage />;
}
