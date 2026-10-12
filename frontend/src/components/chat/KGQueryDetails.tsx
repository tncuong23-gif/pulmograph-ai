import { useState } from "react";
import type { ChatMessage } from "../../types";
import { KGComparisonTable } from "./KGComparisonTable";
import "./kg-query.css";

const modes = { one_hop: "Quan hệ trực tiếp", multi_hop: "Chuỗi quan hệ", path: "Đường liên kết",
  compare: "So sánh", common: "Điểm chung", difference: "Điểm khác" };
const types: Record<string, string> = { Disease: "Bệnh", DiseaseSubtype: "Thể bệnh", Syndrome: "Hội chứng",
  Symptom: "Triệu chứng", ClinicalSign: "Dấu hiệu", Medication: "Thuốc", DrugClass: "Nhóm thuốc", ActiveIngredient: "Hoạt chất" };

export function KGQueryDetails({ message, busy, onConfirm }: {
  message: ChatMessage; busy: boolean; onConfirm?: (ids: string[]) => void;
}) {
  const data = message.metadata;
  const clarification = data?.kg_clarification;
  const [choices, setChoices] = useState<Record<number, string>>({});
  if (!data?.kg_query && !data?.kg_comparison && !clarification) return null;
  const selection = clarification?.groups.map((_, index) => choices[index] || "") ?? [];
  return <section className="kg-query-details" aria-label="Thông tin truy xuất và bằng chứng">
    {data?.kg_query?.mode && !clarification && <p className="kg-query-mode">KG · {modes[data.kg_query.mode]}</p>}
    {data?.kg_comparison && <KGComparisonTable comparison={data.kg_comparison} />}
    {clarification?.can_confirm && <fieldset disabled={busy || !onConfirm}>
      <legend>Xác nhận tên cần tra cứu</legend>
      {clarification.groups.map((group, index) => <label key={index}>
        <span>{group.mention}</span>
        <select aria-label={`Thực thể ${index + 1}`} value={choices[index] || ""}
          onChange={event => setChoices(current => ({ ...current, [index]: event.target.value }))}>
          <option value="">Chọn tên phù hợp…</option>
          {group.candidates.map(candidate => <option key={candidate.id} value={candidate.id}>
            {candidate.name} ({types[candidate.type] ?? candidate.type})
          </option>)}
        </select>
        {(group.candidate_count ?? 0) > group.candidates.length && <small>Danh sách được rút gọn. Bạn có thể viết lại câu hỏi với tên đầy đủ.</small>}
      </label>)}
      <button className="primary-button" type="button"
        disabled={!onConfirm || busy || !selection.length || selection.some(id => !id) || new Set(selection).size !== selection.length}
        onClick={() => onConfirm?.(selection)}>Xác nhận và truy vấn</button>
      {!onConfirm && <small>Lượt xác nhận này đã kết thúc. Hãy dùng lượt mới nhất hoặc gửi lại câu hỏi.</small>}
    </fieldset>}
    {!!data?.kg_query?.warnings?.length && <details>
      <summary>Giới hạn dữ liệu</summary>
      <ul>{data.kg_query.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
    </details>}

  </section>;
}
