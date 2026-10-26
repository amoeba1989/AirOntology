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
test("异常跳点断开，不画跨城的直线", async () => {
  const { trailSegments } = await import("../src/map-utils.js");
  assert.deepEqual(trailSegments([p(1),p(2,116.00001),p(3,117),p(4,117.00001)],p(4).timestamp,10), [
    [p(1),p(2,116.00001)], [p(3,117),p(4,117.00001)],
  ]);
});
test("ArcGIS 深灰底图默认开放旧版，可选令牌切换新版服务", async () => {
  const { darkBasemapConfig } = await import("../src/map-basemap.js");
  assert.match(darkBasemapConfig().base,/World_Dark_Gray_Base/);
  assert.match(darkBasemapConfig().reference,/World_Dark_Gray_Reference/);
  assert.match(darkBasemapConfig('a+b').base,/token=a%2Bb/);
  assert.equal(darkBasemapConfig('key').reference,null);
});
test("切换卫星底图往返时恢复业务坐标", async () => {
  const { wgs84ToGcj02, gcj02ToWgs84 } = await import("../src/amap-basemap.js");
  const display = wgs84ToGcj02(39.9045,116.4077);
  const original = gcj02ToWgs84(...display);
  assert.ok(Math.abs(original[0]-39.9045) < 1e-6);
  assert.ok(Math.abs(original[1]-116.4077) < 1e-6);
});
