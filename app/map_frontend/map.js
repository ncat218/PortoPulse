/* No server requests on pan/zoom, no base-map replacement on A/B changes. */
(function (global) {
  "use strict";
  const CELL = 0.004;
  function boundsOf(coords) {
    return coords.reduce((b, p) => [Math.min(b[0],p[0]),Math.min(b[1],p[1]),
      Math.max(b[2],p[0]),Math.max(b[3],p[1])], [Infinity,Infinity,-Infinity,-Infinity]);
  }
  function intersects(a,b) { return a[0]<=b[2] && a[2]>=b[0] && a[1]<=b[3] && a[3]>=b[1]; }
  function cells(box, visit) {
    for(let x=Math.floor(box[0]/CELL);x<=Math.floor(box[2]/CELL);x++)
      for(let y=Math.floor(box[1]/CELL);y<=Math.floor(box[3]/CELL);y++) visit(x+":"+y);
  }
  function makeIndex(roads) {
    const grid=new Map(), boxes=[];
    roads.forEach((row,i) => {
      const box=boundsOf(row[0]);boxes.push(box);
      cells(box,key => { if(!grid.has(key)) grid.set(key,[]);grid.get(key).push(i); });
    });
    return { query(box) {
      const found=new Set();
      // A user can zoom out far beyond Porto; never iterate a world-sized grid.
      const count=(Math.floor(box[2]/CELL)-Math.floor(box[0]/CELL)+1)*
        (Math.floor(box[3]/CELL)-Math.floor(box[1]/CELL)+1);
      if(count>10000) boxes.forEach((b,i) => {if(intersects(b,box)) found.add(i);});
      else cells(box,key => (grid.get(key)||[]).forEach(i => {if(intersects(boxes[i],box)) found.add(i);}));
      return found;
    }};
  }
  // Export pure index helpers for the Node regression test; no browser required.
  if(typeof module!=="undefined" && module.exports) {module.exports={boundsOf,intersects,makeIndex};return;}

  const post=(type,extra) => global.parent.postMessage({isStreamlitMessage:true,type,...extra},"*");
  let map, args, roads=[], index, dataset=null, requested=null, sequence=0;
  let visible=new Map(), overlayGroup, overlaySignature=null, fitted=null, frame=null;
  const message=document.getElementById("message");
  function emit(kind, point=null) {
    post("streamlit:setComponentValue",{dataType:"json",value:{dataset_id:dataset,kind,
      sequence:++sequence,instance:instanceId,last_clicked:point,last_object_clicked:null}});
  }
  const instanceId=String(Date.now())+"-"+Math.random().toString(36).slice(2);
  function popup(row) {
    const table=document.createElement("table");table.className="road-detail";
    const labels=["Mã cạnh","Tình trạng","Tốc độ ước lượng (km/h)","Tốc độ tham chiếu (km/h)","Số chuyến","Số taxi","Số ngày"];
    const values=[row[1],args.status_labels[row[2]],...row.slice(4,9)];
    labels.forEach((label,i) => {
      const tr=document.createElement("tr"), th=document.createElement("th"),td=document.createElement("td");
      th.textContent=label;td.textContent=values[i]??"Chưa có";tr.append(th,td);table.append(tr);
    });
    return table;
  }
  function roadLayer(row,weight=4,pane) {
    const layer=L.polyline(row[0].map(p=>[p[1],p[0]]),{color:row[3],weight,opacity:.85,
      pane:pane||(row[2]==="unknown"?"roadsUnknown":"roadsKnown"),smoothFactor:0});
    layer.bindTooltip(()=>String(row[1])+" · "+args.status_labels[row[2]]);
    layer.bindPopup(()=>popup(row));return layer;
  }
  function redraw() {
    frame=null;if(!index) return;
    const b=map.getBounds().pad(.12);
    const wanted=index.query([b.getWest(),b.getSouth(),b.getEast(),b.getNorth()]);
    for(const [i,layer] of visible) if(!wanted.has(i)) {map.removeLayer(layer);visible.delete(i);}
    for(const i of wanted) if(!visible.has(i)) visible.set(i,roadLayer(roads[i]).addTo(map));
    message.textContent="";
  }
  function schedule() {if(frame===null) frame=requestAnimationFrame(redraw);}
  function applyOverlay(overlay) {
    const signature=JSON.stringify(overlay);
    if(signature===overlaySignature) return;
    overlaySignature=signature;overlayGroup.clearLayers();
    for(const item of overlay.markers||[]) L.marker([item.lat,item.lon],{icon:L.divIcon({
      className:"",iconSize:[28,28],iconAnchor:[14,14],html:'<div class="point" style="background:'+item.color+'">'+item.role+'</div>'
    })}).addTo(overlayGroup);
    for(const row of overlay.route||[]) {
      const points=row[0].map(p=>[p[1],p[0]]);
      L.polyline(points,{color:"#2563eb",weight:11,opacity:.95,pane:"routeOutline",interactive:false,smoothFactor:0}).addTo(overlayGroup);
      roadLayer(row,5,"routeCore").setStyle({opacity:1}).addTo(overlayGroup);
    }
    for(const gap of overlay.connectors||[]) {
      L.polyline(gap,{color:"#64748b",weight:2,dashArray:"5 5",pane:"routeCore"})
        .bindTooltip("Khoảng nối tới đường · không tính vào ETA").addTo(overlayGroup);
      L.circleMarker(gap[1],{radius:3,color:"#64748b",fill:true,pane:"routeCore"}).addTo(overlayGroup);
    }
    if(overlay.fit_id && overlay.fit_id!==fitted && overlay.bounds?.length) {
      fitted=overlay.fit_id;map.fitBounds(overlay.bounds,{padding:[35,35],maxZoom:18,animate:false});
    }
  }
  global.addEventListener("message", event => {
    if(event.source!==global.parent || event.data?.type!=="streamlit:render") return;
    args=event.data.args;
    document.body.style.height=args.height+"px";
    post("streamlit:setFrameHeight",{height:args.height});
    if(!global.L) {message.textContent="Không tải được thư viện bản đồ. Kiểm tra kết nối Internet rồi tải lại trang.";return;}
    if(!map) {
      map=L.map("map",{preferCanvas:true}).setView(args.center,14);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,
        attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
      for(const [name,z] of [["roadsUnknown",410],["roadsKnown",420],["routeOutline",440],["routeCore",450]])
        map.createPane(name).style.zIndex=z;
      overlayGroup=L.featureGroup().addTo(map);
      map.on("moveend zoomend",schedule);
      map.on("click",e => {if(args.pick_mode!=="Xem bản đồ") emit("click",{lat:e.latlng.lat,lng:e.latlng.lng});});
      new ResizeObserver(()=>{map.invalidateSize({pan:false});schedule();}).observe(document.getElementById("map"));
    }
    map.getContainer().style.cursor=args.pick_mode==="Xem bản đồ"?"":"crosshair";
    if(args.dataset_id!==dataset) {
      if(args.roads) {
        for(const layer of visible.values()) map.removeLayer(layer);
        visible.clear();roads=args.roads;index=makeIndex(roads);dataset=args.dataset_id;requested=null;
        schedule();emit("ready");
      } else if(requested!==args.dataset_id) {
        requested=args.dataset_id;dataset=null;emit("request_roads");
      }
    }
    applyOverlay(args.overlay);schedule();
  });
  post("streamlit:componentReady",{apiVersion:1});
})(typeof window!=="undefined"?window:globalThis);
