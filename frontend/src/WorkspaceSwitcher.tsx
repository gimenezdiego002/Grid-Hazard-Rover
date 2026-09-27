import { Bot, Building2, Shield } from "lucide-react";

export type WorkspaceMode = "operations" | "company" | "rover";

const options = [
  { mode: "operations" as const, label: "Operations dashboard", short: "Operations", icon: Shield },
  { mode: "company" as const, label: "Company portal", short: "Company", icon: Building2 },
  { mode: "rover" as const, label: "Rover simulation", short: "Rover demo", icon: Bot },
];

export default function WorkspaceSwitcher({
  mode,
  onSelect,
}: {
  mode: WorkspaceMode;
  onSelect: (mode: WorkspaceMode) => void;
}) {
  return (
    <div className="workspace-switcher" aria-label="Dashboard workspace">
      {options.map(({ mode: option, label, short, icon: Icon }) => (
        <button
          key={option}
          className={mode === option ? "active" : ""}
          aria-label={label}
          aria-pressed={mode === option}
          onClick={() => onSelect(option)}
        >
          <Icon size={14} />
          <span>{short}</span>
        </button>
      ))}
    </div>
  );
}
