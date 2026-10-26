// ArcGIS Dark Gray Canvas。未配置令牌时使用 Esri 仍开放的旧版栅格服务；
// 配置 VITE_ARCGIS_TOKEN 后切换至新版 Static Basemap Tiles 服务。
const LEGACY = 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas';
const MODERN = 'https://static-map-tiles-api.arcgis.com/arcgis/rest/services/static-basemap-tiles-service/v1/arcgis/dark-gray/static/tile/{z}/{y}/{x}';
export const ESRI_ATTRIBUTION = '&copy; Esri, HERE, Garmin, OpenStreetMap contributors';

export function darkBasemapConfig(token = '') {
  if (token) return { base: `${MODERN}?token=${encodeURIComponent(token)}`, reference: null, source: 'ArcGIS 深灰底图' };
  return {
    base: `${LEGACY}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    reference: `${LEGACY}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
    source: 'ArcGIS 深灰底图',
  };
}
