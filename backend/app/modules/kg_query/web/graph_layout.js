/* Deterministic radial start plus a small, dependency-free force simulation. */
(function (root) {
  function create(nodes, edges) {
    const ids = new Set(nodes.map((node) => node.id));
    const neighbors = new Map(nodes.map((node) => [node.id, new Set()]));
    for (const edge of edges) {
      if (!ids.has(edge.source) || !ids.has(edge.target) || edge.source === edge.target) continue;
      neighbors.get(edge.source).add(edge.target);
      neighbors.get(edge.target).add(edge.source);
    }
    // A query anchor takes priority; otherwise the most connected node is central.
    const rootNode = [...nodes].sort((a, b) =>
      Number(Boolean(b.linked)) - Number(Boolean(a.linked)) ||
      neighbors.get(b.id).size - neighbors.get(a.id).size ||
      String(a.id).localeCompare(String(b.id)))[0];
    const centerId = rootNode?.id;
    const levels = new Map(centerId === undefined ? [] : [[centerId, 0]]);
    const queue = centerId === undefined ? [] : [centerId];
    for (let i = 0; i < queue.length; i++) {
      for (const id of neighbors.get(queue[i])) {
        if (levels.has(id)) continue;
        levels.set(id, levels.get(queue[i]) + 1);
        queue.push(id);
      }
    }
    // Breadth-first order keeps connected concepts near the hub. Pack a large
    // neighborhood over several compact rings instead of one huge circle.
    const ordered = [...queue, ...nodes.map(node => node.id).filter(id => !levels.has(id))];
    const positions = new Map([[centerId, { x: 0, y: 0, vx: 0, vy: 0, radius: 0 }]]);
    let offset = 1, ringIndex = 1;
    while (offset < ordered.length) {
      const radius = 145 + (ringIndex - 1) * 118;
      const capacity = Math.max(1, Math.floor(2 * Math.PI * radius / 125));
      const ring = ordered.slice(offset, offset + capacity);
      ring.forEach((id, i) => {
        const angle = 2 * Math.PI * i / ring.length - Math.PI / 2 + ringIndex * .37;
        positions.set(id, { x: radius * Math.cos(angle), y: radius * Math.sin(angle), vx: 0, vy: 0, radius });
      });
      offset += ring.length;
      ringIndex++;
    }
    const links = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target) && edge.source !== edge.target);
    return { positions, links, centerId };
  }
  function step(layout, pinnedId = null) {
    const points = [...layout.positions.entries()];
    const forces = new Map(points.map(([id]) => [id, { x: 0, y: 0 }]));
    const root = layout.positions.get(layout.centerId);
    for (let i = 0; i < points.length; i++) {
      const [id, a] = points[i], force = forces.get(id);
      const dx = a.x - (layout.centerId === pinnedId ? root.x : 0);
      const dy = a.y - (layout.centerId === pinnedId ? root.y : 0);
      const d = Math.max(1, Math.hypot(dx, dy));
      const radial = id === layout.centerId ? -.65 : (a.radius - d) * .009;
      force.x += dx / d * radial; force.y += dy / d * radial;
      for (let j = i + 1; j < points.length; j++) {
        const [otherId, b] = points[j];
        let vx = b.x - a.x, vy = b.y - a.y;
        if (vx === 0 && vy === 0) { vx = 1; vy = 1; }
        const distance = Math.hypot(vx, vy);
        const strength = Math.min(8, 11000 / (distance * distance));
        const fx = vx / distance * strength, fy = vy / distance * strength;
        force.x -= fx; force.y -= fy;
        forces.get(otherId).x += fx; forces.get(otherId).y += fy;
      }
    }
    for (const link of layout.links) {
      const a = layout.positions.get(link.source), b = layout.positions.get(link.target);
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.max(1, Math.hypot(dx, dy));
      const strength = Math.max(-3, Math.min(3, (d - 155) * .008));
      const fx = dx / d * strength, fy = dy / d * strength;
      forces.get(link.source).x += fx; forces.get(link.source).y += fy;
      forces.get(link.target).x -= fx; forces.get(link.target).y -= fy;
    }
    for (const [id, point] of points) {
      if (id === pinnedId) { point.vx = 0; point.vy = 0; continue; }
      const force = forces.get(id);
      point.vx = Math.max(-14, Math.min(14, (point.vx + force.x) * .78));
      point.vy = Math.max(-14, Math.min(14, (point.vy + force.y) * .78));
      point.x += point.vx; point.y += point.vy;
    }
    // A final collision pass guarantees the circles remain apart at rest.
    for (let pass = 0; pass < 4; pass++) for (let i = 0; i < points.length; i++) for (let j = i + 1; j < points.length; j++) {
      const [idA, a] = points[i], [idB, b] = points[j];
      let dx = b.x - a.x, dy = b.y - a.y, distance = Math.hypot(dx, dy);
      if (distance >= 114) continue;
      if (distance < .01) { dx = 1; dy = 0; distance = 1; }
      const push = (114 - distance) / (idA === pinnedId || idB === pinnedId ? 1 : 2);
      if (idA !== pinnedId) { a.x -= dx / distance * push; a.y -= dy / distance * push; }
      if (idB !== pinnedId) { b.x += dx / distance * push; b.y += dy / distance * push; }
    }
  }
  const api = { create, step };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.KGGraphLayout = api;
})(typeof window !== "undefined" ? window : globalThis);
