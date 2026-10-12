const $ = (id) => document.getElementById(id);
const state = { pairs: [], selected: null, reviews: {}, payload: null, filename: "kg_import.json", preview: null, previewToken: null, choices: {}, reviewPayload: null };
try { state.reviews = JSON.parse(localStorage.getItem("kg_duplicate_reviews_v1") || "{}"); } catch (_) { state.reviews = {}; }

function el(tag, cls, value) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (value != null) node.textContent = String(value);
  return node;
}
function feedback(id, message, error = false) {
  $(id).textContent = message;
  $(id).classList.toggle("error", error);
}
function empty(container, icon, title, description) {
  container.replaceChildren();
  const box = el("div", "welcome");
  box.append(el("span", "", icon), el("strong", "", title), el("p", "", description));
  container.append(box);
}
async function jsonRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    const detail = (data.errors || []).map((issue) => `${issue.code}: ${issue.message}`).slice(0, 4).join("; ");
    throw new Error(detail || data.error || `HTTP ${response.status}`);
  }
  return data;
}
function download(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("tab-graph").addEventListener("click", () => switchTab("graph"));
$("tab-file").addEventListener("click", () => switchTab("file"));
function switchTab(tab) {
  $("graphSection").classList.toggle("hidden", tab !== "graph");
  $("fileSection").classList.toggle("hidden", tab !== "file");
  for (const name of ["graph", "file"]) {
    $("tab-" + name).classList.toggle("active", tab === name);
    $("tab-" + name).setAttribute("aria-selected", String(tab === name));
  }
}
$("scanMode").addEventListener("change", () => {
  if ($("scanMode").value === "embedding" && Number($("scanLimit").value) > 500) $("scanLimit").value = "500";
});
$("scanBtn").addEventListener("click", scan);
$("pairFilter").addEventListener("input", renderPairs);
$("exportReviews").addEventListener("click", () => {
  download({ format: "kg_duplicate_review_v1", exported_at: new Date().toISOString(),
    reviews: state.pairs.filter((p) => state.reviews[p.key]).map((p) => ({ entity_a: p.a.id, entity_b: p.b.id,
      decision: state.reviews[p.key], method: p.method, score: p.score })) }, "kg_duplicate_reviews.json");
});
async function scan() {
  const btn = $("scanBtn");
  btn.disabled = true;
  feedback("scanFeedback", "Đang đọc thực thể và tìm các cặp ứng viên…");
  try {
    const params = new URLSearchParams({ mode: $("scanMode").value, max_entities: $("scanLimit").value,
      min_score: $("minScore").value,
      entity_type: $("entityType").value.trim() });
    const data = await jsonRequest("/modules/kg-explorer/api/review/scan?" + params);
    state.pairs = data.pairs;
    state.selected = null;
    $("scanSummary").classList.remove("hidden");
    $("scannedCount").textContent = data.scanned;
    $("pairCount").textContent = data.pairs_total;
    updateReviewed();
    renderPairs();
    empty($("pairDetail"), "▤", "Chọn một cặp", "Tên, alias, tài liệu và quan hệ sẽ xuất hiện ở đây.");
    feedback("scanFeedback", data.truncated
      ? `Hiển thị tối đa 300 cặp; phạm vi quét có giới hạn. Có thể lọc loại thực thể hoặc quét theo từng phạm vi.`
      : `Đã hoàn tất. ${data.pairs_total} cặp ứng viên cần đánh giá.`);
  } catch (error) { feedback("scanFeedback", error.message, true); }
  finally { btn.disabled = false; }
}
function updateReviewed() {
  $("reviewedCount").textContent = state.pairs.filter((p) => state.reviews[p.key]).length;
}
function renderPairs() {
  const container = $("pairList");
  const filter = $("pairFilter").value.trim().toLocaleLowerCase("vi");
  const pairs = state.pairs.filter((p) => [p.a.id, p.b.id, p.a.name, p.b.name].some((s) => s.toLocaleLowerCase("vi").includes(filter)));
  container.replaceChildren();
  if (!pairs.length) { empty(container, "◎", "Không có cặp phù hợp", "Thử đổi bộ lọc hoặc kiểu quét."); return; }
  for (const p of pairs) {
    const row = el("button", "pair-row" + (p.key === state.selected ? " selected" : ""));
    row.type = "button";
    const top = el("div", "pair-top");
    top.append(el("span", "", p.method === "exact" ? "KHỚP TÊN / ALIAS" : "GẦN NGHĨA"),
      el("span", "score", p.score == null ? p.a.type : `${Math.round(p.score * 100)}% · ${p.a.type}`));
    const names = el("div", "pair-names");
    names.append(document.createTextNode(p.a.name), el("span", "", "↔"), document.createTextNode(p.b.name));
    row.append(top, names, el("div", "pair-sub", `${p.a.id} · ${p.b.id} · ${p.reason}`));
    if (state.reviews[p.key]) row.append(el("span", "status-tag " + state.reviews[p.key],
      ({ same: "Cùng khái niệm", different: "Khác khái niệm", uncertain: "Cần xem thêm" })[state.reviews[p.key]]));
    row.addEventListener("click", () => showPair(p));
    container.append(row);
  }
}
async function showPair(pair) {
  state.selected = pair.key;
  renderPairs();
  feedback("scanFeedback", "Đang tải chi tiết hai thực thể…");
  try {
    const [a, b] = await Promise.all([pair.a.id, pair.b.id].map((id) => jsonRequest("/modules/kg-explorer/api/review/entities/" + encodeURIComponent(id))));
    if (state.selected !== pair.key) return;
    const detail = $("pairDetail");
    detail.replaceChildren(el("div", "reason-line", `${pair.reason}${pair.score == null ? "" : ` · độ tương đồng ${Math.round(pair.score * 100)}%`}`));
    const grid = el("div", "compare-grid");
    grid.append(entityCard(a, "THỰC THỂ A"), entityCard(b, "THỰC THỂ B"));
    detail.append(grid);
    const bar = el("div", "decision-bar");
    bar.append(el("span", "pair-sub", "Đánh giá của bạn:"));
    for (const [value, title] of [["same", "Cùng khái niệm"], ["different", "Khác khái niệm"], ["uncertain", "Cần xem thêm"]]) {
      const button = el("button", (value === "different" ? "different " : "") + (state.reviews[pair.key] === value ? "active" : ""), title);
      button.type = "button";
      button.addEventListener("click", () => {
        state.reviews[pair.key] = value;
        localStorage.setItem("kg_duplicate_reviews_v1", JSON.stringify(state.reviews));
        for (const item of bar.querySelectorAll("button")) item.classList.remove("active");
        button.classList.add("active");
        updateReviewed(); renderPairs();
      });
      bar.append(button);
    }
    detail.append(bar);
    feedback("scanFeedback", "Chi tiết đã tải. Đánh giá chỉ được lưu trong trình duyệt và file xuất.");
  } catch (error) { feedback("scanFeedback", error.message, true); }
}
function entityCard(entity, title) {
  const card = el("article", "entity-card");
  card.append(el("span", "label", title), el("h4", "", entity.canonical_name), el("code", "", entity.id),
    el("div", "type", entity.entity_type));
  const fields = [["Tên khác", entity.aliases], ["Tài liệu nguồn", entity.source_ids]];
  for (const [label, values] of fields) {
    card.append(el("h5", "", label), el("p", "", Array.isArray(values) && values.length ? values.join(" · ") : "Chưa có"));
  }
  card.append(el("h5", "", `Quan hệ (${(entity.relations || []).length}, tối đa 50)`));
  if (!entity.relations?.length) card.append(el("p", "", "Chưa có quan hệ."));
  for (const relation of entity.relations || []) {
    const line = el("div", "relation-line");
    line.append(el("b", "", relation.source_id === entity.id ? "→ " : "← "),
      document.createTextNode(`${relation.predicate} · ${relation.other_name || relation.other_id}`),
      el("small", "pair-sub", ` · ${relation.document_id || "không rõ nguồn"} · ${relation.id || ""}`));
    card.append(line);
  }
  return card;
}

$("jsonFile").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  state.payload = null; state.preview = null; state.previewToken = null; state.choices = {}; state.reviewPayload = null;
  $('fileReviewActions').classList.add('hidden');
  $("previewBtn").disabled = true;
  $("previewSummary").classList.add("hidden");
  $("previewItems").replaceChildren();
  $("uploadGraph").classList.add("hidden");
  $("importPanel").classList.add("hidden");
  feedback("importFeedback", "");
  if (!file) return;
  state.filename = file.name;
  $("fileLabel").textContent = file.name;
  if (file.size > 20 * 1024 * 1024) { feedback("previewFeedback", "File JSON vượt quá 20 MB.", true); return; }
  try {
    const payload = JSON.parse(await file.text());
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("File phải chứa đối tượng JSON.");
    state.payload = payload;
    $("previewBtn").disabled = false;
    renderUploadGraph();
    feedback("previewFeedback", "File đã sẵn sàng. Nhấn “Kiểm tra file” để lập kế hoạch dry-run.");
  } catch (error) { feedback("previewFeedback", `Không đọc được JSON: ${error.message}`, true); }
});
$("previewBtn").addEventListener("click", previewFile);
$("downloadJson").addEventListener("click", () => {
  if (state.payload) download(state.payload, state.filename.replace(/\.json$/i, "") + "_reviewed.json");
});
async function previewFile() {
  if (!state.payload) return;
  const btn = $("previewBtn");
  btn.disabled = true;
  $("jsonFile").disabled = true;
  state.preview = null; state.previewToken = null;
  updateImportPanel();
  feedback("previewFeedback", "Đang kiểm tra schema, Neo4j và ứng viên Qdrant…");
  try {
    const data = await jsonRequest("/modules/kg-explorer/api/review/preview", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.payload) });
    state.preview = data;
    state.reviewPayload = structuredClone(state.payload); state.choices = {};
    $('fileReviewActions').classList.remove('hidden');
    $('fileReviewStatus').textContent = data.review_status==='reviewed' ? `Đã duyệt · ${new Date(data.reviewed_at).toLocaleString('vi-VN')}` : 'Chưa duyệt nội dung hiện tại';
    $('keepAllFileEntities').disabled = !Object.keys(data.plan?.entity_candidates || {}).length;
    $('downloadJson').textContent = data.review_status==='reviewed' ? 'Tải JSON đã duyệt' : 'Tải JSON hiện tại';
    state.previewToken = data.preview_token || null;
    const plan = data.plan || {};
    $("previewSummary").classList.remove("hidden");
    $("previewCreate").textContent = plan.entities?.create ?? 0;
    $("previewLinked").textContent = Object.keys(plan.entity_links || {}).length;
    $("previewCandidates").textContent = Object.keys(plan.entity_candidates || {}).length;
    renderPreview(plan);
    renderUploadGraph(plan);
    updateImportPanel();
    feedback("previewFeedback", `Đã kiểm tra ${data.document_id || "tài liệu"}. Chọn cách xử lý các ứng viên, rồi bấm Lưu duyệt tài liệu.`);
  } catch (error) {
    $("previewSummary").classList.add("hidden");
    $("previewItems").replaceChildren();
    updateImportPanel();
    feedback("previewFeedback", error.message, true);
  } finally { btn.disabled = false; $("jsonFile").disabled = false; }
}
function renderPreview(plan) {
  const target = $("previewItems");
  target.replaceChildren();
  const candidates = Object.entries(plan.entity_candidates || {});
  const linked = Object.entries(plan.entity_links || {});
  const entities = new Map((state.payload.entities || []).map((entity) => [entity.id, entity]));
  if (linked.length) {
    const card = el("div", "preview-card");
    card.append(el("h3", "", "Đã liên kết tự động theo tên / alias"), el("p", "", "Các ID đầu vào này khớp chính xác với thực thể đã có."));
    for (const [id, chosen] of linked) card.append(el("div", "relation-line", `${entities.get(id)?.canonical_name || id} · ${id} → ${chosen}`));
    target.append(card);
  }
  if (!candidates.length) {
    target.append(el("div", "empty-note", "Không còn ứng viên embedding cần duyệt trong lần kiểm tra này."));
    return;
  }
  const card = el("div", "preview-card");
  card.append(el("h3", "", "Ứng viên gần nghĩa cần quyết định"),
    el("p", "", "Chọn ID Neo4j hiện có nếu cùng khái niệm, hoặc giữ riêng. Sau đó bấm Lưu duyệt tài liệu."));
  for (const [id, options] of candidates) {
    const row = el("div", "suggestion-row");
    const label = el("div");
    label.append(el("strong", "", entities.get(id)?.canonical_name || id), el("small", "", id));
    const select = el("select", "decision-select");
    select.setAttribute("aria-label", `Quyết định cho ${id}`);
    select.append(new Option("Chưa quyết định", ""));
    for (const option of options) {
      if (option.link_allowed === false) { label.append(el("small", "", `Khác loại: ${option.canonical_name} (${option.entity_type}). Sửa JSON nếu cùng khái niệm; chỉ giữ riêng khi khác khái niệm.`)); continue; }
      select.append(new Option(`${option.matched_name || option.entity_id} · ${option.entity_id} · ${Math.round(option.score * 100)}%`, option.entity_id));
    }
    select.append(new Option("Giữ là thực thể riêng", "new"));
    select.value = state.payload.entity_link_decisions?.[id] || "";
    select.addEventListener("change", () => {
      const decisions = state.payload.entity_link_decisions ||= {};
      if (select.value) { decisions[id] = select.value; state.choices[id] = select.value; }
      else { delete decisions[id]; delete state.choices[id]; }
      $('fileReviewStatus').textContent = 'Có lựa chọn chưa lưu';
      $('downloadJson').textContent = 'Tải JSON hiện tại';
      state.previewToken = null;
      updateImportPanel();
      feedback("previewFeedback", "Đã cập nhật lựa chọn. Bấm “Lưu duyệt tài liệu” để kiểm tra và lưu trạng thái.");
    });
    row.append(label, select); card.append(row);
  }
  target.append(card);
}

$("keepAllFileEntities").addEventListener("click", () => {
  const candidates = state.preview?.plan?.entity_candidates || {};
  const decisions = state.payload.entity_link_decisions ||= {};
  for (const [id, options] of Object.entries(candidates)) { if(options.some(c => c.link_allowed === false)) continue; decisions[id] = "new"; state.choices[id] = "new"; }
  state.previewToken = null;
  $("downloadJson").textContent = "Tải JSON hiện tại";
  $("fileReviewStatus").textContent = `Đã chọn giữ riêng ứng viên cùng loại; khác loại cần duyệt từng mục; chưa lưu`;
  renderPreview(state.preview.plan); updateImportPanel();
});
$("saveFileReview").addEventListener("click", async () => {
  if (!state.reviewPayload) return;
  const remaining = Object.keys(state.preview?.plan?.entity_candidates || {}).filter(id => !state.choices[id]);
  if (remaining.length) { feedback("previewFeedback", `Còn ${remaining.length} thực thể chưa chọn cách xử lý.`, true); return; }
  const controls = ["saveFileReview", "keepAllFileEntities", "previewBtn", "jsonFile", "importBtn"];
  controls.forEach(id => $(id).disabled = true);
  document.querySelectorAll('.decision-select').forEach(select => select.disabled = true);
  feedback("previewFeedback", "Đang kiểm tra và lưu duyệt tài liệu…");
  try {
    const data = await jsonRequest("/modules/kg-explorer/api/review/decisions", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({payload:state.reviewPayload, choices:state.choices})});
    state.payload = data.payload; state.reviewPayload = structuredClone(data.payload); state.choices = {};
    state.preview = data; state.previewToken = data.preview_token;
    $("downloadJson").textContent = "Tải JSON đã duyệt";
    $("fileReviewStatus").textContent = `Đã duyệt · ${new Date(data.reviewed_at).toLocaleString('vi-VN')}`;
    $("previewCreate").textContent = data.plan.entities?.create ?? 0;
    $("previewLinked").textContent = Object.keys(data.plan.entity_links || {}).length;
    $("previewCandidates").textContent = Object.keys(data.plan.entity_candidates || {}).length;
    renderPreview(data.plan); renderUploadGraph(data.plan);
    feedback("previewFeedback", "Đã lưu trạng thái duyệt tại backend. Có thể tải JSON đã duyệt hoặc xác nhận import.");
  } catch (error) { feedback("previewFeedback", error.message, true); }
  finally {
    controls.forEach(id => $(id).disabled = false);
    document.querySelectorAll('.decision-select').forEach(select => select.disabled = false);
    $("keepAllFileEntities").disabled = !Object.keys(state.preview?.plan?.entity_candidates || {}).length;
    updateImportPanel();
  }
});

function updateImportPanel() {
  if (!state.payload) { $("importPanel").classList.add("hidden"); return; }
  $("importPanel").classList.remove("hidden");
  const candidates = Object.keys(state.preview?.plan?.entity_candidates || {}).length;
  $("importBtn").disabled = !state.previewToken;
  $("importMessage").textContent = state.previewToken
    ? `Dry-run hợp lệ: ${state.preview.document_id} · tạo ${state.preview.plan?.entities?.create ?? 0} thực thể và ${state.preview.plan?.relations?.create ?? 0} quan hệ. Hãy xem đồ thị và xác nhận khi sẵn sàng.`
    : candidates ? `Còn ${candidates} ứng viên trong bản xem trước. Chọn cách xử lý rồi bấm “Lưu duyệt tài liệu”.`
      : "Cần hoàn thành dry-run với nội dung JSON hiện tại trước khi import.";
}

$("importBtn").addEventListener("click", async () => {
  if (!state.payload || !state.previewToken) return;
  const doc = state.preview?.document_id || state.payload.document?.document_id || "tài liệu";
  const nodes = state.preview?.plan?.entities?.create ?? 0;
  const edges = state.preview?.plan?.relations?.create ?? 0;
  if (!window.confirm(`Import ${doc} vào MongoDB và Neo4j?\nDự kiến tạo ${nodes} thực thể và ${edges} quan hệ. Hành động này sẽ ghi dữ liệu thật.`)) return;
  const token = state.previewToken;
  state.previewToken = null;
  updateImportPanel();
  feedback("importFeedback", "Đang ghi dữ liệu vào MongoDB và Neo4j. Không đóng trang cho đến khi có kết quả…");
  try {
    const response = await fetch("/modules/kg-explorer/api/review/import", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payload: state.payload, preview_token: token }) });
    const result = await response.json();
    const issues = (result.errors || []).map((e) => `${e.code}: ${e.message}`).slice(0, 4).join("; ");
    if (!response.ok || result.status !== "completed") {
      throw new Error(`Import ${result.status || "thất bại"}${result.import_id ? ` (${result.import_id})` : ""}. ${issues || result.error || "Kiểm tra log máy chủ."}`);
    }
    feedback("importFeedback", `Đã import ${result.document_id || doc} thành công. Import ID: ${result.import_id}.`);
    $("importMessage").textContent = "Dữ liệu đã được ghi. Muốn import lại, hãy chạy dry-run mới.";
  } catch (error) {
    feedback("importFeedback", `${error.message} Hãy kiểm tra trạng thái import trước khi thử lại.`, true);
  }
});

function svg(tag, attrs = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  return node;
}
$("resetLayout").addEventListener("click", () => state.uploadGraphControl?.fit());
$("uploadZoomIn").addEventListener("click", () => state.uploadGraphControl?.zoom(1.25));
$("uploadZoomOut").addEventListener("click", () => state.uploadGraphControl?.zoom(1 / 1.25));
$("uploadFullscreen").addEventListener("click", async () => { await window.KGGraph.toggleFullscreen($("uploadGraph")); requestAnimationFrame(updateUploadGraphSize); });
function updateUploadGraphSize() {
  const canvas = $("uploadGraph").querySelector(".upload-canvas");
  state.uploadGraphControl?.resize(canvas.clientWidth, canvas.clientHeight);
  $("uploadFullscreen").setAttribute("aria-label", document.fullscreenElement === $("uploadGraph") || $("uploadGraph").classList.contains("kg-fullscreen") ? "Thoát toàn màn hình" : "Toàn màn hình");
}
document.addEventListener("fullscreenchange", () => requestAnimationFrame(updateUploadGraphSize));
window.addEventListener("resize", updateUploadGraphSize);
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && $("uploadGraph").classList.contains("kg-fullscreen")) { $("uploadGraph").classList.remove("kg-fullscreen"); requestAnimationFrame(updateUploadGraphSize); } });
function renderUploadGraph(plan = null) {
  const entities = Array.isArray(state.payload?.entities) ? state.payload.entities : [];
  const relations = Array.isArray(state.payload?.relations) ? state.payload.relations : [];
  const panel = $("uploadGraph"), canvas = $("uploadSvg"), list = $("uploadEdges");
  panel.classList.remove("hidden"); canvas.replaceChildren(); list.replaceChildren();
  const links = plan?.entity_links || {};
  const nodes = new Map();
  for (const entity of entities) {
    if (typeof entity.id !== "string") continue;
    const id = links[entity.id] || entity.id;
    if (!nodes.has(id)) nodes.set(id, { id, name: String(entity.canonical_name || id), type: String(entity.type || "Entity"), linked: id !== entity.id });
  }
  const edges = relations.filter((r) => r && typeof r.source === "string" && typeof r.target === "string").map((r) => {
    const source = links[r.source] || r.source, target = links[r.target] || r.target;
    if (!nodes.has(source)) nodes.set(source, { id: source, name: source, type: "Đã có trong Neo4j", linked: true });
    if (!nodes.has(target)) nodes.set(target, { id: target, name: target, type: "Đã có trong Neo4j", linked: true });
    return { source, target, predicate: String(r.type || "RELATION"), id: String(r.id || "") };
  });
  $("graphInfo").textContent = `${nodes.size} nút · ${edges.length} quan hệ${plan ? " · đã áp dụng ID liên kết" : " · chưa kiểm tra"}`;
  if (!nodes.size) { list.append(el("div", "empty-note", "File chưa có thực thể để vẽ.")); return; }
  const visibleEdges = edges.slice(0, 80);
  const visibleIds = new Set(visibleEdges.flatMap((r) => [r.source, r.target]));
  if (!visibleEdges.length) for (const id of [...nodes.keys()].slice(0, 80)) visibleIds.add(id);
  const visible = [...visibleIds].map((id) => nodes.get(id));
  const detail = $("uploadDetail");
  const buttons = [];
  let controller;
  function select(index) {
    controller?.highlightEdge(index);
    buttons.forEach((button, i) => button.classList.toggle("active", i === index));
    buttons[index]?.scrollIntoView({ block: "nearest" });
    const r = visibleEdges[index];
    if (r) detail.textContent = `${nodes.get(r.source).name}  →  ${r.predicate}  →  ${nodes.get(r.target).name} · ${r.id}`;
  }
  visibleEdges.forEach((r, index) => {
    const button = el("button", "upload-edge"); button.type = "button";
    button.append(document.createTextNode(`${nodes.get(r.source).name} → ${r.predicate} → ${nodes.get(r.target).name}`),
      el("small", "", `${r.source} → ${r.target} · ${r.id}`));
    button.addEventListener("click", () => select(index));
    list.append(button); buttons.push(button);
  });
  controller = window.KGGraph.render(canvas, { nodes: visible, edges: visibleEdges.map((r) => ({
    source: r.source, target: r.target, type: r.predicate })),
    width: panel.querySelector(".upload-canvas").clientWidth, height: panel.querySelector(".upload-canvas").clientHeight,
    onEdge: select, onNode: (node) => { detail.textContent = `${node.name} · ${node.type} · ${node.id}`; }
  });
  state.uploadGraphControl = controller;
  detail.textContent = "Chọn nút hoặc cạnh để xem tên đầy đủ và ID.";
  if (edges.length > 80) list.append(el("div", "empty-note", `Đang vẽ 80/${edges.length} quan hệ. File gốc vẫn được import đầy đủ.`));
  if (!edges.length) list.append(el("div", "empty-note", "File chưa có quan hệ. Có thể xem các nút ở đồ thị."));
}
