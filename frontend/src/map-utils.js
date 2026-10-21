// Only observed points are connected; gaps are deliberately left visible.
export function mergeTrail(previous, incoming, limit = 300) {
  const points = new Map();
  for (const p of [...previous, ...incoming]) {
    const time = Date.parse(p.timestamp);
    if (
      !Number.isFinite(time) ||
      !Number.isFinite(p.lat) ||
      !Number.isFinite(p.lon) ||
      Math.abs(p.lat) > 90 ||
      Math.abs(p.lon) > 180
    )
      continue;
    points.set(time, { lat: p.lat, lon: p.lon, timestamp: p.timestamp });
  }
  return [...points.entries()]
    .sort((a, b) => a[0] - b[0])
    .slice(-limit)
    .map(([, p]) => p);
}
export function trailSegments(points, cutoff, maxGapSeconds) {
  const end = Date.parse(cutoff);
  const segments = [];
  let current = [];
  for (const p of mergeTrail([], points)) {
    if (Date.parse(p.timestamp) > end) continue;
    if (
      current.length &&
      Date.parse(p.timestamp) - Date.parse(current.at(-1).timestamp) >
        maxGapSeconds * 1000
    ) {
      if (current.length > 1) segments.push(current);
      current = [];
    }
    current.push(p);
  }
  if (current.length > 1) segments.push(current);
  return segments;
}
