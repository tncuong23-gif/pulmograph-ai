/* Radial, force-directed SVG graph with local pan and zoom. */
(function (root) {
  const NS = "http://www.w3.org/2000/svg";
  const palette = ["#a83484", "#d05e32", "#1679aa", "#478328", "#aa7516", "#6755ae", "#168b76"];
  const element = (tag, attrs = {}) => {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    return node;
  };
  function color(type) {
    let hash = 0;
    for (const ch of String(type || "Entity")) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
    return palette[hash % palette.length];
  }
  function splitLabel(value) {
    const title = String(value || "").trim();
    if (title.length <= 13) return [title, ""];
    const at = Math.max(1, title.lastIndexOf(" ", 13));
    const a = title.slice(0, at).trim(), rest = title.slice(at).trim();
    return [a.slice(0, 13), rest.length > 13 ? rest.slice(0, 12) + "…" : rest];
  }
  function render(svg, options) {
    svg._kgGraphAbort?.abort();
    svg._kgGraphStop?.();
    const listeners = new AbortController();
    svg._kgGraphAbort = listeners;
    svg.replaceChildren();
    const nodes = options.nodes || [], edges = options.edges || [];
    let width = Math.max(320, options.width || svg.clientWidth || 760);
    let height = options.height || 500;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    if (!nodes.length) return { highlightEdge() {}, zoom() {}, fit() {}, resize() {} };
    const layout = root.KGGraphLayout.create(nodes, edges);
    const positions = layout.positions;
    for (let i = 0; i < 110; i++) root.KGGraphLayout.step(layout);
    let settleFrame = 0, disposed = false;
    svg._kgGraphStop = () => { disposed = true; if (settleFrame) cancelAnimationFrame(settleFrame); };
    const names = new Map(nodes.map((node) => [node.id, node]));
    const defs = element("defs"), marker = element("marker", { id: `arrow-${svg.id}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto" });
    marker.append(element("path", { d: "M 0 1 L 9 5 L 0 9 z", fill: "#64748b" }));
    defs.append(marker); svg.append(defs);
    const view = element("g"), edgeLayer = element("g"), nodeLayer = element("g");
    view.append(edgeLayer, nodeLayer); svg.append(view);
    const edgeParts = [], groups = new Map();
    let scale = 1, tx = 0, ty = 0, selected = -1;
    const applyView = () => view.setAttribute("transform", `translate(${tx},${ty}) scale(${scale})`);
    function bounds() {
      const values = [...positions.values()];
      return { minX: Math.min(...values.map(p => p.x)) - 68,
               maxX: Math.max(...values.map(p => p.x)) + 68,
               minY: Math.min(...values.map(p => p.y)) - 68,
               maxY: Math.max(...values.map(p => p.y)) + 68 };
    }
    function fit() {
      const b = bounds();
      scale = Math.max(.06, Math.min(1.2, (width - 40) / (b.maxX - b.minX), (height - 40) / (b.maxY - b.minY)));
      tx = width / 2 - (b.minX + b.maxX) / 2 * scale;
      ty = height / 2 - (b.minY + b.maxY) / 2 * scale;
      applyView();
    }
    function focus() {
      const b = bounds();
      if (b.maxX - b.minX < width * 1.15 && b.maxY - b.minY < height * 1.15) { fit(); return; }
      const center = positions.get(layout.centerId);
      scale = width < 600 ? 1 : 1.2;
      tx = width / 2 - center.x * scale;
      ty = height / 2 - center.y * scale;
      applyView();
    }
    function resize(nextWidth, nextHeight) {
      width = Math.max(320, nextWidth || width);
      height = Math.max(240, nextHeight || height);
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      focus();
    }
    function zoom(multiplier, px = width / 2, py = height / 2) {
      const next = Math.max(.06, Math.min(3.2, scale * multiplier));
      const ratio = next / scale;
      tx = px - (px - tx) * ratio;
      ty = py - (py - ty) * ratio;
      scale = next;
      applyView();
    }
    function graphPoint(ev) {
      const rect = svg.getBoundingClientRect();
      return { x: (ev.clientX - rect.left) * width / rect.width,
               y: (ev.clientY - rect.top) * height / rect.height };
    }
    function redraw() {
      for (const item of edgeParts) {
        const a = positions.get(item.edge.source), b = positions.get(item.edge.target);
        if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.max(1, Math.hypot(dx, dy));
        const ux = dx / d, uy = dy / d;
        const start = Math.min(item.edge.source === layout.centerId ? 60 : 50, d / 3);
        const end = Math.min(item.edge.target === layout.centerId ? 60 : 52, d / 3);
        const x1 = a.x + ux * start, y1 = a.y + uy * start;
        const x2 = b.x - ux * end, y2 = b.y - uy * end;
        for (const line of [item.line, item.hit]) {
          line.setAttribute("x1", x1); line.setAttribute("y1", y1);
          line.setAttribute("x2", x2); line.setAttribute("y2", y2);
        }
        item.label.setAttribute("x", (x1 + x2) / 2);
        item.label.setAttribute("y", (y1 + y2) / 2 - 8);
      }
      for (const [id, group] of groups) {
        const p = positions.get(id);
        group.setAttribute("transform", `translate(${p.x},${p.y})`);
      }
    }
    function settle(iterations, pinnedId = null) {
      if (settleFrame) cancelAnimationFrame(settleFrame);
      let remaining = iterations;
      function tick() {
        if (disposed) return;
        for (let i = 0; i < 3 && remaining > 0; i++, remaining--) root.KGGraphLayout.step(layout, pinnedId);
        redraw();
        settleFrame = remaining > 0 ? requestAnimationFrame(tick) : 0;
      }
      settleFrame = requestAnimationFrame(tick);
    }
    function highlightEdge(index) {
      selected = index;
      edgeParts.forEach((item) => item.group.classList.toggle("selected-edge", item.index === index));
    }
    edges.forEach((edge, index) => {
      if (!positions.has(edge.source) || !positions.has(edge.target)) return;
      const group = element("g", { class: "neo-edge", "data-edge-index": index, tabindex: 0, role: "button",
        "aria-label": `${names.get(edge.source).name} ${edge.type} ${names.get(edge.target).name}` });
      const line = element("line", { class: "neo-line", "marker-end": `url(#arrow-${svg.id})` });
      const hit = element("line", { class: "neo-edge-hit" });
      const label = element("text", { class: "neo-relation", "text-anchor": "middle" });
      label.textContent = edge.type;
      // Labels appear on selection for large graphs, avoiding text collisions.
      if (edges.length > 24) group.classList.add("dense");
      group.append(line, hit, label);
      group.addEventListener("click", () => { highlightEdge(index); options.onEdge?.(index); });
      group.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); group.dispatchEvent(new Event("click")); } });
      edgeLayer.append(group); edgeParts.push({ edge, index, group, line, hit, label });
    });
    nodes.forEach((node) => {
      const group = element("g", { class: "neo-node", tabindex: 0, role: "button", "aria-label": `${node.name} (${node.type})` });
      const circle = element("circle", { r: node.id === layout.centerId ? 55 : 46, fill: color(node.type), class: [node.linked ? "linked" : "", node.id === layout.centerId ? "center" : ""].join(" ").trim() });
      const lines = splitLabel(node.name);
      const a = element("text", { class: "neo-name", y: lines[1] ? -4 : 5, "text-anchor": "middle" }); a.textContent = lines[0];
      group.append(circle, a);
      if (lines[1]) { const b = element("text", { class: "neo-name", y: 15, "text-anchor": "middle" }); b.textContent = lines[1]; group.append(b); }
      const title = element("title"); title.textContent = `${node.name} · ${node.type} · ${node.id}`; group.append(title);
      let dragging = false, start = null;
      group.addEventListener("pointerdown", (ev) => {
        if (ev.button !== 0) return;
        dragging = true; start = graphPoint(ev); group.setPointerCapture(ev.pointerId);
        group.classList.add("dragging"); nodeLayer.append(group); ev.stopPropagation(); ev.preventDefault();
      });
      group.addEventListener("pointermove", (ev) => {
        if (!dragging) return;
        const p = graphPoint(ev);
        const point = positions.get(node.id);
        point.x = (p.x - tx) / scale; point.y = (p.y - ty) / scale;
        point.vx = 0; point.vy = 0;
        redraw(); settle(36, node.id);
      });
      function release(ev) {
        if (!dragging) return;
        dragging = false; group.classList.remove("dragging");
        if (group.hasPointerCapture(ev.pointerId)) group.releasePointerCapture(ev.pointerId);
        settle(105);
        if (start && Math.hypot(graphPoint(ev).x - start.x, graphPoint(ev).y - start.y) < 5) options.onNode?.(node);
      }
      group.addEventListener("pointerup", release);
      group.addEventListener("pointercancel", release);
      group.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); options.onNode?.(node); } });
      nodeLayer.append(group); groups.set(node.id, group);
    });
    let panning = null;
    svg.addEventListener("pointerdown", (ev) => {
      if (ev.target !== svg && ev.target !== view) return;
      panning = { id: ev.pointerId, x: ev.clientX, y: ev.clientY, tx, ty };
      svg.setPointerCapture(ev.pointerId);
    }, { signal: listeners.signal });
    svg.addEventListener("pointermove", (ev) => {
      if (!panning || panning.id !== ev.pointerId) return;
      const rect = svg.getBoundingClientRect();
      tx = panning.tx + (ev.clientX - panning.x) * width / rect.width;
      ty = panning.ty + (ev.clientY - panning.y) * height / rect.height;
      applyView();
    }, { signal: listeners.signal });
    const stopPan = (ev) => { if (panning?.id === ev.pointerId) panning = null; };
    svg.addEventListener("pointerup", stopPan, { signal: listeners.signal });
    svg.addEventListener("pointercancel", stopPan, { signal: listeners.signal });
    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault(); const p = graphPoint(ev); zoom(ev.deltaY < 0 ? 1.15 : 1 / 1.15, p.x, p.y);
    }, { passive: false, signal: listeners.signal });
    redraw(); focus();
    if (selected >= 0) highlightEdge(selected);
    return { highlightEdge, zoom, fit, resize };
  }
  async function toggleFullscreen(panel) {
    if (document.fullscreenElement === panel) { await document.exitFullscreen(); return; }
    if (panel.classList.contains("kg-fullscreen")) { panel.classList.remove("kg-fullscreen"); return; }
    if (panel.requestFullscreen) {
      try { await panel.requestFullscreen(); return; } catch (_) { /* Use the CSS fallback. */ }
    }
    panel.classList.add("kg-fullscreen");
  }
  root.KGGraph = { render, color, toggleFullscreen };
})(window);
