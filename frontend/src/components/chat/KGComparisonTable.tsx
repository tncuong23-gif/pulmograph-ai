import { FactCitations } from "./EvidenceSources";
import { useState } from "react";
import type { KGComparison, KGComparisonFact } from "../../types";

const propertyLabels: Record<string, string> = {
  negated: "Phủ định", negation: "Phủ định", polarity: "Chiều khẳng định", population: "Đối tượng",
  condition: "Điều kiện", conditions: "Điều kiện", severity: "Mức độ", timeframe: "Thời gian",
  certainty: "Mức chắc chắn", dose: "Liều", route: "Đường dùng", context: "Ngữ cảnh",
};
function propertyValue(value: unknown): string {
  if (value === true) return "Có";
  if (value === false) return "Không";
  if (value === null) return "Chưa xác định";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function FactSources({ facts }: { facts: KGComparisonFact[] }) {
  if (!facts.length) return <span className="kg-comparison-missing">Chưa tìm thấy trong dữ liệu truy xuất</span>;
  const assertions = facts.flatMap(fact => fact.assertions ?? []);
  const hasNegation = assertions.some(assertion => assertion.properties?.negated === true || assertion.properties?.negation === true);
  const hasProperties = assertions.some(assertion => !assertion.properties_valid || Object.keys(assertion.properties ?? {}).length > 0);
  return <>
    <span>Đã ghi nhận quan hệ</span>
    {hasNegation && <strong className="kg-comparison-qualifier">Có phủ định trong nguồn</strong>}
    {hasProperties && <small>Cần đọc thuộc tính và điều kiện nguồn bên dưới.</small>}
    <details>
      <summary>Điều kiện và nguồn</summary>
      {facts.map((fact, factIndex) => <div key={factIndex} className="kg-comparison-fact">
        <p>Quan hệ nguồn: {fact.subject.name} → {fact.object.name}</p>
        {!fact.assertions?.length && <p>Chưa có thuộc tính nguồn để kiểm tra.</p>}
        {fact.assertions?.map((assertion, index) => {
          const evidence = fact.evidence?.filter(source => source.doc_id === assertion.document_id
            && assertion.evidence_ids?.includes(source.evidence_id ?? "")) ?? [];
          return <div key={index} className="kg-comparison-assertion">
            <strong>Bằng chứng nguồn <FactCitations evidence={evidence}/></strong>
            {!assertion.properties_valid ? <p>Thuộc tính nguồn chưa hợp lệ; cần kiểm tra.</p>
              : Object.keys(assertion.properties).length ? <dl>
                {Object.entries(assertion.properties).map(([key, value]) => <div key={key}>
                  <dt>{propertyLabels[key] ?? key}</dt><dd>{propertyValue(value)}</dd>
                </div>)}
              </dl> : <p>Chưa có thuộc tính điều kiện.</p>}
            
            {evidence.map((source, sourceIndex) => <blockquote key={sourceIndex}>{source.text ?? "Chưa có trích đoạn văn bản."}</blockquote>)}
            {!evidence.length && <small>Chưa có trích đoạn văn bản cho quan hệ này.</small>}
          </div>;
        })}
      </div>)}
    </details>
  </>;
}

export function KGComparisonTable({ comparison }: { comparison: KGComparison }) {
  const [filter, setFilter] = useState("all");
  const rows = comparison.rows.filter(row => filter === "all" ||
    (filter === "common" ? row.classification === "common" : row.classification !== "common"));
  return <div className="kg-comparison">
    <p className="kg-comparison-notice">{comparison.notice}</p>
    {comparison.truncated && <p className="kg-comparison-missing">Kết quả đã chạm giới hạn; bảng có thể chưa đầy đủ.</p>}
    {comparison.mode === "compare" && comparison.rows.length > 0 && <div className="kg-comparison-filters" aria-label="Lọc hàng đối chiếu">
      {[["all", "Tất cả"], ["common", "Điểm chung"], ["difference", "Điểm khác / cần kiểm tra"]].map(([value, label]) =>
        <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}
    </div>}
    {rows.length ? <div className="kg-comparison-scroll" tabIndex={0} role="region" aria-label="Bảng so sánh, có thể cuộn ngang">
      <table>
        <caption>Đối chiếu dữ liệu giữa {comparison.entities.map(entity => entity.name).join(" và ")}</caption>
        <thead><tr><th scope="col">Tiêu chí / đặc điểm</th>
          {comparison.entities.map(entity => <th scope="col" key={entity.id}>{entity.name}</th>)}
          <th scope="col">Kết quả đối chiếu</th>
        </tr></thead>
        <tbody>{rows.map((row, index) => <tr key={`${row.criterion}:${row.predicate}:${row.feature.id}:${row.direction}:${index}`}>
          <th scope="row"><strong>{row.feature.name}</strong><small>{row.criterion_label}</small></th>
          {row.cells.map(cell => <td key={cell.entity_id}>
            <FactSources facts={cell.fact_indices.map(position => comparison.facts[position]).filter(Boolean)} />
          </td>)}
          <td><span className={row.classification === "common" ? "kg-comparison-common" : "kg-comparison-missing"}>{row.label}</span></td>
        </tr>)}</tbody>
      </table>
    </div> : <p>Chưa có hàng phù hợp trong phần dữ liệu được trả về. Điều này không khẳng định có hay không có điểm chung/khác biệt về y khoa.</p>}
  </div>;
}
