/* 全国 鳥獣出没マップ
   背景は地理院タイルと NASA GIBS（どちらも鍵不要）。点は収録対象の出没情報。 */

const SPECIES = [
  ["tsukinowaguma", "ツキノワグマ", "#ef4444"],
  ["higuma", "ヒグマ", "#7c2d12"],
  ["inoshishi", "イノシシ", "#f59e0b"],
  ["shika", "ニホンジカ", "#10b981"],
  ["unknown", "その他・不明", "#64748b"],
];
const CATEGORY = [
  ["sighting", "目撃・出没"], ["trace", "痕跡"], ["damage", "被害"],
  ["injury", "人身被害"], ["capture", "捕獲"], ["unknown", "不明"],
];

// 昨日の日付（GIBS の日次タイルは当日ぶんが揃っていないことがある）
const gibsDate = new Date(Date.now() - 864e5).toISOString().slice(0, 10);

const GSI = '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">地理院タイル</a>';
const NASA = 'NASA EOSDIS GIBS / VIIRS';

const BASES = {
  pale:  { label: "淡色地図", attribution: GSI, maxzoom: 18,
           tiles: ["https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"] },
  std:   { label: "地図", attribution: GSI, maxzoom: 18,
           tiles: ["https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png"] },
  photo: { label: "空中写真", attribution: GSI, maxzoom: 18,
           tiles: ["https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg"] },
  sat:   { label: "衛星（前日）", attribution: NASA, maxzoom: 9,
           tiles: ["https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/" +
                   "VIIRS_SNPP_CorrectedReflectance_TrueColor/default/" + gibsDate +
                   "/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg"] },
};

const state = {
  base: "pale",
  species: new Set(SPECIES.map(s => s[0])),
  category: new Set(CATEGORY.map(c => c[0])),
  year: "",
};

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    // クラスタの数字を描くのに字形が要る。外部 CDN に貼らず 1 ファイルだけ同梱している。
    glyphs: "vendor/fonts/{fontstack}/{range}.pbf",
    sources: {},
    layers: [{ id: "bg", type: "background", paint: { "background-color": "#eef2f6" } }],
  },
  center: [138.5, 37.6],
  zoom: 4.6,
  maxZoom: 17,
  hash: true,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
map.addControl(new maplibregl.ScaleControl({ maxWidth: 120 }), "bottom-right");
map.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), "top-right");

function setBase(key) {
  state.base = key;
  for (const k of Object.keys(BASES)) {
    if (map.getLayer("base-" + k)) map.removeLayer("base-" + k);
    if (map.getSource("base-" + k)) map.removeSource("base-" + k);
  }
  const b = BASES[key];
  map.addSource("base-" + key, {
    type: "raster", tiles: b.tiles, tileSize: 256, maxzoom: b.maxzoom, attribution: b.attribution,
  });
  const before = map.getLayer("clusters") ? "clusters" : undefined;
  map.addLayer({ id: "base-" + key, type: "raster", source: "base-" + key }, before);
  document.querySelectorAll("#bases button").forEach(el => {
    el.setAttribute("aria-pressed", String(el.dataset.key === key));
  });
}

function filterExpression() {
  const f = ["all",
    ["in", ["get", "s"], ["literal", [...state.species]]],
    ["in", ["get", "c"], ["literal", [...state.category]]],
  ];
  if (state.year) f.push(["==", ["slice", ["get", "d"], 0, 4], state.year]);
  return f;
}

function applyFilter() {
  const src = map.getSource("sightings");
  if (!src || !window.__all) return;
  const sp = state.species, ca = state.category, yr = state.year;
  const feats = window.__all.features.filter(ft => {
    const p = ft.properties;
    return sp.has(p.s) && ca.has(p.c) && (!yr || p.d.slice(0, 4) === yr);
  });
  src.setData({ type: "FeatureCollection", features: feats });
  document.getElementById("count").textContent = feats.length.toLocaleString("ja-JP");
}

function buildControls(years) {
  const bases = document.getElementById("bases");
  for (const [key, b] of Object.entries(BASES)) {
    const btn = document.createElement("button");
    btn.textContent = b.label;
    btn.dataset.key = key;
    btn.setAttribute("aria-pressed", String(key === state.base));
    btn.addEventListener("click", () => setBase(key));
    bases.appendChild(btn);
  }
  const spBox = document.getElementById("species");
  for (const [key, label, color] of SPECIES) {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" checked value="${key}">` +
      `<span class="swatch" style="background:${color}"></span>${label}`;
    l.querySelector("input").addEventListener("change", e => {
      e.target.checked ? state.species.add(key) : state.species.delete(key);
      applyFilter();
    });
    spBox.appendChild(l);
  }
  const caBox = document.getElementById("category");
  for (const [key, label] of CATEGORY) {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" checked value="${key}">${label}`;
    l.querySelector("input").addEventListener("change", e => {
      e.target.checked ? state.category.add(key) : state.category.delete(key);
      applyFilter();
    });
    caBox.appendChild(l);
  }
  const sel = document.getElementById("year");
  for (const y of years) {
    const o = document.createElement("option");
    o.value = y; o.textContent = y + " 年";
    sel.appendChild(o);
  }
  sel.addEventListener("change", e => { state.year = e.target.value; applyFilter(); });

  const jumps = document.getElementById("jumps");
  // 収録している地域だけを回れるようにする（他県はデータが無く、白紙に見えるため）
  for (const [label, center, zoom] of [
    ["秋田県", [140.35, 39.72], 8.2],
    ["京都府", [135.55, 35.30], 8.6],
    ["山口県", [131.55, 34.20], 8.4],
    ["北海道", [142.20, 43.30], 6.8],
    ["全国", [138.5, 37.6], 4.6],
  ]) {
    const b = document.createElement("button");
    b.textContent = label;
    b.addEventListener("click", () => map.easeTo({ center, zoom, duration: 900 }));
    jumps.appendChild(b);
  }

  const toggle = document.getElementById("toggle");
  toggle.addEventListener("click", () => {
    const panel = document.getElementById("panel");
    const open = panel.style.display !== "none";
    panel.style.display = open ? "none" : "block";
    toggle.setAttribute("aria-expanded", String(!open));
    toggle.textContent = open ? "絞り込みを出す" : "絞り込みを隠す";
  });
}

const colorBySpecies = ["match", ["get", "s"],
  ...SPECIES.flatMap(([k, , c]) => [k, c]), "#64748b"];

map.on("load", async () => {
  setBase(state.base);

  const res = await fetch("data/sightings.min.geojson");
  const data = await res.json();
  window.__all = data;

  map.addSource("sightings", {
    type: "geojson", data, cluster: true, clusterRadius: 46, clusterMaxZoom: 11,
  });

  map.addLayer({
    id: "clusters", type: "circle", source: "sightings", filter: ["has", "point_count"],
    paint: {
      "circle-color": ["step", ["get", "point_count"], "#fca5a5", 50, "#f87171", 300, "#dc2626"],
      "circle-radius": ["step", ["get", "point_count"], 13, 50, 18, 300, 25],
      "circle-opacity": 0.85,
      "circle-stroke-width": 1.5, "circle-stroke-color": "#ffffff",
    },
  });
  map.addLayer({
    id: "cluster-count", type: "symbol", source: "sightings", filter: ["has", "point_count"],
    layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12,
              "text-font": ["Noto Sans Regular"] },
    paint: { "text-color": "#ffffff" },
  });
  map.addLayer({
    id: "points", type: "circle", source: "sightings", filter: ["!", ["has", "point_count"]],
    paint: {
      "circle-color": colorBySpecies,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 3.5, 10, 5.5, 14, 8],
      "circle-opacity": 0.9,
      "circle-stroke-width": 1, "circle-stroke-color": "rgba(255,255,255,.9)",
    },
  });

  const years = [...new Set(data.features.map(f => f.properties.d.slice(0, 4)))]
    .filter(Boolean).sort().reverse();
  buildControls(years);
  document.getElementById("count").textContent = data.features.length.toLocaleString("ja-JP");

  const labelOf = (list, key) => (list.find(x => x[0] === key) || [null, key])[1];

  map.on("click", "points", e => {
    const p = e.features[0].properties;
    const rows = [
      ["日付", p.d], ["獣種", labelOf(SPECIES, p.s)], ["区分", labelOf(CATEGORY, p.c)],
      ["場所", [p.p, p.m].filter(Boolean).join(" ")], ["頭数", p.n],
    ].filter(([, v]) => v);
    new maplibregl.Popup({ maxWidth: "300px" })
      .setLngLat(e.features[0].geometry.coordinates)
      .setHTML(`<b>${p.d}</b>` +
        rows.slice(1).map(([k, v]) => `${k}: ${escapeHtml(v)}<br>`).join("") +
        (p.t ? `<div style="margin-top:4px;color:#4b5563">${escapeHtml(p.t)}</div>` : "") +
        (p.a ? `<div style="margin-top:6px;font-size:11px;color:#6b7280">出典: ${escapeHtml(p.a)}</div>` : ""))
      .addTo(map);
  });
  map.on("click", "clusters", async e => {
    const id = e.features[0].properties.cluster_id;
    const zoom = await map.getSource("sightings").getClusterExpansionZoom(id);
    map.easeTo({ center: e.features[0].geometry.coordinates, zoom });
  });
  for (const layer of ["points", "clusters"]) {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  }

  document.getElementById("credit").innerHTML =
    'データ出典: 秋田県・京都府・山口県・札幌市・室蘭市・石狩市・上砂川町（CC BY 4.0）。背景は地理院タイルと NASA EOSDIS GIBS。' +
    '<a href="https://github.com/yasumorishima/japan-wildlife-sightings">リポジトリ</a>・' +
    '<a href="THIRD-PARTY-NOTICES.txt">ライセンス表示</a>';
});

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
