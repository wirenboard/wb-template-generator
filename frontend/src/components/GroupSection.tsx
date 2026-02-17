import { useState, type ReactNode } from 'react';

interface GroupSectionProps {
  title: string;
  children: ReactNode;
  /** Управляемый режим: если передан — внутренний state не используется */
  expanded?: boolean;
  onToggle?: () => void;
}

/** Сворачиваемая секция группы */
export default function GroupSection({ title, children, expanded: controlledExpanded, onToggle }: GroupSectionProps) {
  const [localExpanded, setLocalExpanded] = useState(true);
  const isControlled = controlledExpanded !== undefined;
  const expanded = isControlled ? controlledExpanded : localExpanded;

  const handleToggle = () => {
    if (isControlled) {
      onToggle?.();
    } else {
      setLocalExpanded((v) => !v);
    }
  };

  return (
    <div className="border border-gray-200 rounded-lg mb-2 overflow-hidden">
      <div
        onClick={handleToggle}
        className="bg-gray-50 px-3 py-1.5 cursor-pointer flex items-center gap-2 select-none"
      >
        <span className="text-gray-400 text-xs w-3 text-center">
          {expanded ? '\u25BE' : '\u25B8'}
        </span>
        <span className="text-xs font-medium text-gray-700">{title}</span>
      </div>
      {expanded && <div className="divide-y divide-gray-100">{children}</div>}
    </div>
  );
}
