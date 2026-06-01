import {
  BarChart3,
  BookOpen,
  Boxes,
  Calendar,
  CheckCircle,
  Clock,
  Code2,
  Cpu,
  Database,
  FlaskConical,
  Globe2,
  GraduationCap,
  HardDrive,
  LayoutDashboard,
  Monitor,
  NotebookTabs,
  Server,
  Shield,
  UserCheck,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";

const byType: Record<string, LucideIcon> = {
  jupyter: NotebookTabs,
  vscode: Code2,
  netbeans: Monitor,
  mysql: Database,
  wordpress: Globe2,
  lamp: Server,
  custom: Boxes,
  admin: Shield,
  teacher: Users,
  stats: BarChart3,
  cpu: Cpu,
  flask: FlaskConical,
  dashboard: LayoutDashboard,
  classroom: GraduationCap,
  student: UserCheck,
  assignment: BookOpen,
  audit: Clock,
  storage: HardDrive,
  config: Wrench,
  calendar: Calendar,
  healthy: CheckCircle,
};

export const icons = byType;

export function RuntimeIcon({ type, className }: { type?: string | null; className?: string }) {
  const key = (type || "").toLowerCase();
  const Icon = byType[key] || (key.includes("code") ? Code2 : key.includes("python") ? NotebookTabs : Boxes);
  return <Icon className={className} aria-hidden="true" />;
}
