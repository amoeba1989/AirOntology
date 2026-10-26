// WGS84 只用于业务数据与距离计算；国内高德地图显示使用 GCJ-02。
const PI = Math.PI;
const A = 6378245.0;
const EE = 0.006693421622965943;

function latitudeOffset(x, y) {
  return -100 + 2*x + 3*y + .2*y*y + .1*x*y + .2*Math.sqrt(Math.abs(x))
    + (20*Math.sin(6*x*PI) + 20*Math.sin(2*x*PI))*2/3
    + (20*Math.sin(y*PI) + 40*Math.sin(y/3*PI))*2/3
    + (160*Math.sin(y/12*PI) + 320*Math.sin(y*PI/30))*2/3;
}

function longitudeOffset(x, y) {
  return 300 + x + 2*y + .1*x*x + .1*x*y + .1*Math.sqrt(Math.abs(x))
    + (20*Math.sin(6*x*PI) + 20*Math.sin(2*x*PI))*2/3
    + (20*Math.sin(x*PI) + 40*Math.sin(x/3*PI))*2/3
    + (150*Math.sin(x/12*PI) + 300*Math.sin(x/30*PI))*2/3;
}

export function wgs84ToGcj02(lat, lon) {
  if (lon < 72.004 || lon > 137.8347 || lat < .8293 || lat > 55.8271) return [lat, lon];
  const x = lon - 105, y = lat - 35;
  const sinLat = Math.sin(lat/180*PI);
  const magic = 1 - EE*sinLat*sinLat;
  const sqrt = Math.sqrt(magic);
  const dLat = latitudeOffset(x,y)*180/((A*(1-EE))/(magic*sqrt)*PI);
  const dLon = longitudeOffset(x,y)*180/(A/sqrt*Math.cos(lat/180*PI)*PI);
  return [lat+dLat, lon+dLon];
}

export function gcj02ToWgs84(lat, lon) {
  let guessLat = lat, guessLon = lon;
  for (let i = 0; i < 3; i++) {
    const [convertedLat, convertedLon] = wgs84ToGcj02(guessLat, guessLon);
    guessLat += lat - convertedLat;
    guessLon += lon - convertedLon;
  }
  return [guessLat, guessLon];
}

export async function attachAmapSatellite(leafletMap, key, host) {
  if (!key) return null;
  window._AMapSecurityConfig = {serviceHost: host || `${location.origin}/_AMapService`};
  if (!window.AMap) {
    await new Promise((resolve,reject) => {
      const script=document.createElement('script');
      script.src=`https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(key)}`;
      script.onload=resolve;
      script.onerror=()=>reject(new Error('高德 JS API 加载失败'));
      document.head.appendChild(script);
    });
  }
  const AMap=window.AMap;
  if (!AMap?.TileLayer?.Satellite) throw new Error('高德卫星图层不可用');
  const center=leafletMap.getCenter();
  const basemap=new AMap.Map('amap-basemap',{
    center:[center.lng,center.lat],zoom:leafletMap.getZoom(),
    layers:[new AMap.TileLayer.Satellite()],
    dragEnable:false,zoomEnable:false,scrollWheel:false,doubleClickZoom:false,
  });
  const sync=()=>{
    const p=leafletMap.getCenter();
    basemap.resize();
    basemap.setZoomAndCenter(leafletMap.getZoom(),[p.lng,p.lat],false);
  };
  leafletMap.on('move zoom resize',sync);
  return () => {leafletMap.off('move zoom resize',sync);basemap.destroy();};
}
