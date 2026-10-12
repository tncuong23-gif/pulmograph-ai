import { FileText, ImageIcon } from "lucide-react";
import { SuggestedQuestions } from "./SuggestedQuestions";
import { vi } from "../../i18n/vi";
export function WelcomeScreen({
  onSelect,
}: {
  onSelect: (question: string) => void;
}) {
  return (
    <div className="welcome-screen">
      <div className="welcome-intro">
        <img className="welcome-illustration" src="/favicon.svg" alt="" aria-hidden="true" />
        <div className="welcome-eyebrow">
          <span>TRỢ LÝ SỨC KHỎE HÔ HẤP</span>
        </div>
        <h2>
          {vi.welcome}
          <br />
          <span>{vi.welcomeAccent}</span>
        </h2>
        <p>{vi.intro}</p>
      </div>
      <div className="suggestions-heading">
        <span>Bắt đầu với một câu hỏi</span>
        <span>GỢI Ý CHO BẠN</span>
      </div>
      <SuggestedQuestions onSelect={onSelect} />
      <div className="context-tip">
        <div className="context-tip-icons">
          <FileText size={17} />
          <ImageIcon size={17} />
        </div>
        <p>
          Thêm bệnh án{" "}
          <span>để cung cấp thêm bối cảnh cho câu hỏi.</span>
        </p>
      </div>
    </div>
  );
}
