/* Measure real browser -> Streamlit -> route Canvas using immutable real export.
   The Leaflet map reference is injected only into test responses, never production.
   Fresh headless profile/temporary port; does not use the user's running app. */
const fs=require('node:fs'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),run=path.join(root,'artifacts/latency_20261101');fs.mkdirSync(run,{recursive:true});
const python=process.env.PORTOFLOW_TEST_PYTHON||path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
const output=process.argv[2]||path.join(run,'measurement.json');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const A=[41.132423,-8.604602],B=[41.135227,-8.607853];
(async()=>{
 let app,browser;const log=fs.openSync(path.join(run,'streamlit.log'),'w');
 try{
  const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
  app=spawn(python,['-m','streamlit','run',path.join(root,'app/streamlit_app.py'),'--server.headless=true','--server.address=127.0.0.1',
   '--server.port='+port,'--server.fileWatcherType=none','--browser.gatherUsageStats=false'],{cwd:root,windowsHide:true,stdio:['ignore',log,log],
   env:{...process.env,PORTOFLOW_ARTIFACTS:path.join(root,'runs/preview_20261027'),PYTHONPATH:path.join(root,'src')}});
  const url='http://127.0.0.1:'+port;
  for(let i=0;i<150;i++){try{if((await fetch(url+'/_stcore/health')).ok)break;}catch{}await delay(200);}
  browser=await chromium.launch({headless:true,executablePath:process.env.PORTOFLOW_TEST_BROWSER||undefined});
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('https://tile.openstreetmap.org/**',r=>r.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9XkAAAAASUVORK5CYII=','base64')}));
  await page.route('**/map.js*',r=>{
   let code=fs.readFileSync(path.join(root,'app/map_frontend/map.js'),'utf8');
   code=code.replace('args=event.data.args;','args=event.data.args;global.__testArgs=args;');
   code=code.replace('map=L.map("map",{preferCanvas:true}).setView(args.center,14);',
    'map=L.map("map",{preferCanvas:true}).setView(args.center,14);global.__testMap=map;global.__testRenders=[];');
   code=code.replace('applyOverlay(args.overlay);schedule();',
    'applyOverlay(args.overlay);schedule();if(args.overlay.fit_id && args.overlay.route.length)requestAnimationFrame(()=>requestAnimationFrame(()=>global.__testRenders.push({id:args.overlay.fit_id,time:Date.now()})));');
   r.fulfill({status:200,contentType:'text/javascript',body:code});
  });
  const loaded=Date.now();await page.goto(url);
  await page.getByText('Chọn hành trình',{exact:true}).waitFor({timeout:120000});
  await page.getByText('Chọn hành trình',{exact:true}).click();
  let frame;
  for(let i=0;i<300;i++){frame=page.frames().find(f=>f.url().includes('portopulse_map'));if(frame&&await frame.evaluate(()=>!!window.__testMap).catch(()=>false))break;await delay(200);}
  await frame.locator('#message').waitFor({state:'hidden',timeout:60000});
  await frame.waitForFunction(()=>__testArgs.pick_mode==='Chọn điểm A',null,{timeout:15000});
  const initial_ready_ms=Date.now()-loaded,samples=[];
  const clickAt=async coordinates=>{
   const p=await frame.evaluate(ll=>{const p=__testMap.latLngToContainerPoint(ll);return{x:p.x,y:p.y};},coordinates);
   await frame.locator('#map').click({position:p});
  };
  for(let i=0;i<3;i++){
   if(i)await page.getByRole('button',{name:'Chọn lại',exact:true}).click();
   await frame.waitForFunction(()=>__testArgs.pick_mode==='Chọn điểm A',null,{timeout:15000});
   await frame.evaluate(ll=>{__testMap.setView(ll,16,{animate:false});__testRenders=[];},A);await delay(150);
   await clickAt(A);await frame.locator('.point').filter({hasText:'A'}).waitFor({timeout:15000});
   await frame.waitForFunction(()=>__testArgs.pick_mode==='Chọn điểm B',null,{timeout:15000});
   const start=Date.now();await clickAt(B);
   await frame.waitForFunction(()=>__testRenders.length>0,null,{timeout:30000});
   const rendered=await frame.evaluate(()=>__testRenders[0].time);
   samples.push(rendered-start);console.log('B_TO_ROUTE_MS',i+1,samples.at(-1));
  }
  if(errors.length)throw Error(errors.join('\n'));
  const report={scope:'Actual headless browser mouse click B to route overlay after2animation frames; localhost full Streamlit, real22,860edge export.',
   requested_coordinates:{A,B},day_group:'weekday',time_bucket:'00-06',initial_ready_ms,b_to_route_ms:samples,
   target_ms:5000,all_samples_within_target:samples.every(n=>n<=5000),
   limits:['Local machine/browser sample, not universal latency guarantee.','Background map tiles stubbed; Leaflet library still loaded from CDN.',
    'Mouse positions are projected to CSS pixels, so input coordinates can differ slightly from screenshots.','Test-only JS exposes map and timestamp; production source is not modified.']};
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');console.log(report);
 }finally{if(browser)await browser.close();if(app)app.kill();fs.closeSync(log);}
})().catch(e=>{console.error(e);process.exitCode=1;});
