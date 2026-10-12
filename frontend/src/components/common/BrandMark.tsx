export function BrandMark({ large = false }: { large?: boolean }) {
  return <span className={`brand-mark ${large ? "large" : ""}`} aria-hidden="true"><img src="/favicon.svg" alt="" /></span>;
}
