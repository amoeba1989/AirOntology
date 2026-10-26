const {test}=require('node:test');
const assert=require('node:assert/strict');

test('高德显示坐标转换只应用于国内底图，业务经纬度不变',async()=>{
  const {wgs84ToGcj02}=await import('../src/amap-basemap.js');
  const beijing=[39.9045,116.4077];
  const shown=wgs84ToGcj02(...beijing);
  assert.ok(shown[0]>beijing[0] && shown[0]<beijing[0]+.01);
  assert.ok(shown[1]>beijing[1] && shown[1]<beijing[1]+.01);
  assert.deepEqual(beijing,[39.9045,116.4077]);
  assert.deepEqual(wgs84ToGcj02(48.8566,2.3522),[48.8566,2.3522]);
});
