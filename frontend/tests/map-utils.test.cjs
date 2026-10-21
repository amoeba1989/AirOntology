const { test } = require("node:test");
const assert = require("node:assert/strict");
const p = (seconds, lon = 116) => ({
  timestamp: new Date(seconds * 1000).toISOString(),
  lat: 39,
  lon,
});
test("轨迹按观测时间去重排序、限制长度并排除非法坐标", async () => {
  const { mergeTrail } = await import("../src/map-utils.js");
  assert.deepEqual(mergeTrail([p(2), p(1)], [p(2, 117), p(3), p(4, 999)], 2), [
    p(2, 117),
    p(3),
  ]);
});
test("回放不显示未来轨迹，断报不连接为连续飞行", async () => {
  const { trailSegments } = await import("../src/map-utils.js");
  const points = [p(1), p(2), p(30), p(31), p(32)];
  assert.deepEqual(trailSegments(points, p(31).timestamp, 10), [
    [p(1), p(2)],
    [p(30), p(31)],
  ]);
  assert.deepEqual(trailSegments(points, p(1).timestamp, 10), []);
});
