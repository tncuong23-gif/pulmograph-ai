import {
  Activity,
  ArrowUpRight,
  ClipboardList,
  Microscope,
  Stethoscope,
} from "lucide-react";
import { vi } from "../../i18n/vi";
const icons = [Stethoscope, Activity, ClipboardList, Microscope];
export function SuggestedQuestions({
  onSelect,
}: {
  onSelect: (question: string) => void;
}) {
  return (
    <div className="suggestions">
      {vi.suggestions.map((item, i) => {
        const Icon = icons[i];
        return (
          <button
            key={item.question}
            className="suggestion-card"
            onClick={() => onSelect(item.question)}
          >
            <span className="suggestion-top">
              <Icon size={19} strokeWidth={1.7} />
              <span>{item.category}</span>
              <ArrowUpRight className="suggestion-arrow" size={17} />
            </span>
            <span className="suggestion-question">{item.question}</span>
          </button>
        );
      })}
    </div>
  );
}
