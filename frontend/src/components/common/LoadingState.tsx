export function LoadingState({
  label = "Đang tải cuộc trò chuyện…",
}: {
  label?: string;
}) {
  return (
    <div className="loading-state" role="status">
      <span className="loading-bar" />
      <span>{label}</span>
    </div>
  );
}
