import { BrandMark } from "../common/BrandMark";
import { vi } from "../../i18n/vi";
export function TypingIndicator() {
  return (
    <div className="typing-indicator" role="status">
      <BrandMark />
      <div>
        <span>{vi.typing}</span>
        <div className="typing-dots">
          <i />
          <i />
          <i />
        </div>
      </div>
    </div>
  );
}
