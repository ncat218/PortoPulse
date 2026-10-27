/* Optional isolated browser integration. Does not start the Streamlit app.
   Requires Playwright via NODE_PATH and a fixture from benchmark_map.py. */
const fs=require('node:fs'),http=require('node:http'),path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const fixture=JSON.parse(fs.readFileSync(process.argv[2]||path.join(root,'artifacts/map_component/fixture.json'),'utf8'));
const output=process.argv[3]||path.join(root,'reports/map_performance_20261028/browser_check.json');
const harness=`<!doctype html><html><body style="margin:0"><iframe id="component" src="/index.html" style="width:1100px;height:560px;border:0"></iframe>
<script>window.messages=[];addEventListener('message',e=>{if(e.source===document.querySelector('iframe').contentWindow)messages.push(e.data)});
window.sendArgs=a=>document.querySelector('iframe').contentWindow.postMessage({type:'streamlit:render',args:a},location.origin);</script></body></html>`;
const server=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://localhost').pathname;
  if(name==='/harness.html') {res.setHeader('Content-Type','text/html');res.end(harness);return;}
  if(!['/index.html','/map.js'].includes(name)) {res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':'text/html');
  res.end(fs.readFileSync(path.join(root,'app/map_frontend',name.slice(1))));
});
(async()=>{
  let browser;
  try {
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    browser=await chromium.launch({headless:true,executablePath:process.env.PORTOFLOW_TEST_BROWSER||undefined});
    const page=await browser.newPage({viewport:{width:1200,height:700}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    // Tile images are irrelevant to road/protocol verification and can vary online.
    await page.route('https://tile.openstreetmap.org/**',r=>r.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9XkAAAAASUVORK5CYII=','base64')}));
    await page.goto(`http://127.0.0.1:${server.address().port}/harness.html`);
    const waitKind=kind=>page.waitForFunction(k=>messages.some(m=>m.type==='streamlit:setComponentValue'&&m.value.kind===k),kind,{timeout:30000});
    await page.waitForFunction(()=>messages.some(m=>m.type==='streamlit:componentReady'),null,{timeout:30000});
    const started=Date.now();await page.evaluate(a=>sendArgs(a),fixture.initial);await waitKind('ready');
    let frame=page.frames().find(f=>f.url().includes('/index.html'));
    await frame.waitForFunction(()=>document.getElementById('message').textContent==='');
    const readyMs=Date.now()-started;
    await page.evaluate(a=>sendArgs(a),fixture.warm);
    const mapNode=frame.locator('#map');
    await mapNode.evaluate(e=>e.dataset.persisted='yes');
    assert.equal(await frame.locator('.point').count(),2);
    const initialEvents=await page.evaluate(()=>messages.filter(m=>m.type==='streamlit:setComponentValue').length);
    // Both map drag and zoom stay inside the client; do not ask Python to rerun.
    await frame.locator('.leaflet-control-zoom-in').click();
    await page.waitForTimeout(350);
    await mapNode.hover({position:{x:500,y:300}});
    await page.mouse.down();await page.mouse.move(650,350,{steps:6});await page.mouse.up();
    await page.waitForTimeout(350);
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='streamlit:setComponentValue').length),initialEvents,
      JSON.stringify(await page.evaluate(()=>messages.filter(m=>m.type==='streamlit:setComponentValue'))));
    await mapNode.click({position:{x:400,y:220}});await waitKind('click');
    const event=await page.evaluate(()=>messages.filter(m=>m.type==='streamlit:setComponentValue'&&m.value.kind==='click').at(-1).value);
    assert(Number.isFinite(event.last_clicked.lat)&&Number.isFinite(event.last_clicked.lng));
    // Simulated Python rerun sends no roads; iframe DOM and zoom remain intact.
    const zoomBefore=await frame.locator('.leaflet-pane.leaflet-tile-pane').getAttribute('style');
    await page.evaluate(a=>sendArgs({...a,pick_mode:'Xem bản đồ'}),fixture.warm);
    assert.equal(await mapNode.getAttribute('data-persisted'),'yes');
    assert.equal(await frame.locator('.leaflet-pane.leaflet-tile-pane').getAttribute('style'),zoomBefore);
    await mapNode.click({position:{x:350,y:220}});
    await page.waitForTimeout(100);
    assert.equal(await page.evaluate(()=>messages.filter(m=>m.type==='streamlit:setComponentValue'&&m.value.kind==='click').length),1);
    // Bucket change replaces road data without remounting the map.
    const next={...fixture.initial,dataset_id:fixture.initial.dataset_id+'-new-bucket'};
    await page.evaluate(a=>sendArgs(a),next);
    await page.waitForFunction(id=>messages.some(m=>m.type==='streamlit:setComponentValue'&&m.value.dataset_id===id),next.dataset_id);
    assert.equal(await mapNode.getAttribute('data-persisted'),'yes');
    // Iframe/browser reload with an old Python ack must request and receive roads.
    await page.evaluate(()=>{messages=[];document.querySelector('iframe').src='/index.html?reload=1';});
    await page.waitForFunction(()=>messages.some(m=>m.type==='streamlit:componentReady'),null,{timeout:30000});
    await page.evaluate(a=>sendArgs({...a,roads:null}),next);await waitKind('request_roads');
    await page.evaluate(a=>sendArgs(a),next);await waitKind('ready');
    frame=page.frames().find(f=>f.url().includes('/index.html'));
    await frame.waitForFunction(()=>document.getElementById('message').textContent==='');
    assert.equal(await frame.locator('.point').count(),2);
    assert.deepEqual(errors,[]);
    const report={status:'PASS',scope:'Isolated real Leaflet component in headless Chromium; parent simulates Streamlit render messages',
      roads:fixture.initial.roads.length,first_component_render_ms:readyMs,
      checks:['actual Leaflet Canvas rendering','A/B markers','pan/zoom sends no server events','A/B click returns coordinates',
        'warm overlay preserves map DOM and viewport','view-only click sends no server event','bucket switch preserves map DOM',
        'iframe reload requests missing roads and recovers','no JavaScript exceptions'],
      limits:['Tile requests stubbed; no real browser FPS or end-user latency claim.','Full Streamlit Python UI integration covered by AppTest separately.']};
    fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
  } finally {if(browser) await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
