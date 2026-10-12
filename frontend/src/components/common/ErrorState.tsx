import { AlertCircle, RotateCcw } from "lucide-react";
export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
      {onRetry && (
        <button onClick={onRetry}>
          <RotateCcw size={14} /> Thử lại
        </button>
      )}
    </div>
  );
}
