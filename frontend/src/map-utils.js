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
function metersBetween(a, b) {
  const latitude = (a.lat + b.lat) * Math.PI / 360;
  const north = (b.lat - a.lat) * 111_195;
  const east = (b.lon - a.lon) * 111_195 * Math.cos(latitude);
  return Math.hypot(north, east);
}
export function trailSegments(points, cutoff, maxGapSeconds, maxSpeedMps = 120) {
  const end = Date.parse(cutoff);
  const segments = [];
  let current = [];
  for (const p of mergeTrail([], points)) {
    if (Date.parse(p.timestamp) > end) continue;
    const previous = current.at(-1);
    const seconds = previous && (Date.parse(p.timestamp) - Date.parse(previous.timestamp)) / 1000;
    if (previous && (seconds > maxGapSeconds ||
      metersBetween(previous, p) / seconds > maxSpeedMps)) {
      if (current.length > 1) segments.push(current);
      current = [];
    }
    current.push(p);
  }
  if (current.length > 1) segments.push(current);
  return segments;
}
