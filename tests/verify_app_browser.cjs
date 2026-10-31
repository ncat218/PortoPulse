/* Real Streamlit -> component -> Python callback -> updated marker regression.
   Uses a separate synthetic export/temporary localhost port, headless fresh profile.
   Requires Playwright via NODE_PATH; never opens or stops the user's app. */
const fs=require('node:fs'),path=require('node:path'),net=require('node:net');
const {spawn,spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const run=path.join(root,'artifacts/app_browser_click_test');fs.mkdirSync(run,{recursive:true});
const python=process.env.PORTOFLOW_TEST_PYTHON||path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const reportPath=process.env.PORTOFLOW_TEST_REPORT||path.join(run,'result.json');
(async()=>{
  let app,browser,page;const log=fs.openSync(path.join(run,'streamlit.log'),'w');
  const errors=[],consoleMessages=[];let phase='fixture';
  try {
    const fixture=spawnSync(python,[path.join(root,'tests/create_browser_fixture.py'),path.join(run,'export')],{cwd:root,encoding:'utf8',windowsHide:true});
    assert.equal(fixture.status,0,fixture.stdout+'\n'+fixture.stderr);
    const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
    const env={...process.env,PORTOFLOW_ARTIFACTS:path.join(run,'export'),PYTHONPATH:path.join(root,'src'),STREAMLIT_BROWSER_GATHER_USAGE_STATS:'false'};
    app=spawn(python,['-m','streamlit','run',path.join(root,'app/streamlit_app.py'),'--server.headless=true',
      '--server.address=127.0.0.1','--server.port='+port,'--server.fileWatcherType=none','--browser.gatherUsageStats=false'],
      {cwd:root,env,stdio:['ignore',log,log],windowsHide:true});
    phase='startup';const url='http://127.0.0.1:'+port;
    for(let i=0;i<150;i++) {try {if((await fetch(url+'/_stcore/health')).ok) break;}catch{} await delay(200);}
    browser=await chromium.launch({headless:true,executablePath:process.env.PORTOFLOW_TEST_BROWSER||undefined});
    page=await browser.newPage({viewport:{width:1440,height:1100}});
    page.on('pageerror',e=>errors.push(e.message));
    page.on('console',m=>consoleMessages.push(m.type()+': '+m.text()));
    await page.route('https://tile.openstreetmap.org/**',r=>r.fulfill({status:200,contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9XkAAAAASUVORK5CYII=','base64')}));
    await page.goto(url);
    await page.evaluate(()=>{window.mapMessages=[];addEventListener('message',e=>{if(e.data?.isStreamlitMessage)mapMessages.push(e.data);});});
    phase='quality details';
    await page.getByText('Độ phủ dữ liệu trong khung giờ',{exact:true}).waitFor({timeout:60000});
    assert.equal(await page.getByText('Cạnh đã phân loại',{exact:true}).isVisible(),false);
    await page.getByText('Độ phủ dữ liệu trong khung giờ',{exact:true}).click();
    await page.getByText('Cạnh đã phân loại',{exact:true}).waitFor();
    assert.equal(await page.getByText('Cạnh đã phân loại',{exact:true}).isVisible(),true);
    await page.getByText('Độ phủ dữ liệu trong khung giờ',{exact:true}).click();
    const quality=page.getByText('Bản thử nghiệm: QC matching và đánh giá holdout chưa hoàn tất.',{exact:true});
    assert.equal(await quality.isVisible(),false);
    await page.getByText('Nguồn & chất lượng dữ liệu',{exact:true}).click();
    await quality.waitFor();
    assert.equal(await quality.isVisible(),true);
    await page.getByText('Nguồn & chất lượng dữ liệu',{exact:true}).click();
    await page.getByText('Chọn hành trình',{exact:true}).click({timeout:60000});
    await page.getByRole('button',{name:'A · Điểm đi',exact:true}).click();
    let frame;
    for(let i=0;i<150;i++) {frame=page.frames().find(f=>f.url().includes('persistent_map.portopulse_map'));if(frame && await frame.locator('.leaflet-control-zoom-in').count()) break;await delay(200);}
    assert(frame,'Map component iframe not found');
    await frame.locator('#message').waitFor({state:'hidden',timeout:30000});
    await frame.evaluate(()=>{window.renderMessages=[];addEventListener('message',e=>{if(e.data?.type==='streamlit:render')renderMessages.push({mode:e.data.args.pick_mode,markers:e.data.args.overlay.markers});});});
    phase='zoom';for(let i=0;i<3;i++) {await frame.locator('.leaflet-control-zoom-in').click();await delay(350);}
    const map=frame.locator('#map');const dimensions=await map.evaluate(e=>({width:e.clientWidth,height:e.clientHeight}));
    await map.evaluate(e=>e.dataset.persisted='full_app');
    phase='click A';await map.click({position:{x:dimensions.width/2+22,y:dimensions.height/2}});
    await frame.locator('.point').filter({hasText:'A'}).waitFor({timeout:12000});
    phase='click B';await map.click({position:{x:dimensions.width/2+155,y:dimensions.height/2}});
    await frame.locator('.point').filter({hasText:'B'}).waitFor({timeout:15000});
    await page.getByText('Tuyến đề xuất · cân bằng thời gian và quãng đường',{exact:true}).waitFor({timeout:15000});
    assert.equal(await frame.locator('.point').count(),2);
    assert.equal(await map.getAttribute('data-persisted'),'full_app');
    phase='view road popup';
    await delay(200); // fitBounds and Canvas hit regions finish on animation frames.
    const countBefore=await page.evaluate(()=>mapMessages.filter(m=>m.type==='streamlit:setComponentValue').length);
    const aBox=await frame.locator('.point').filter({hasText:'A'}).boundingBox(),mapBox=await map.boundingBox();
    await map.click({position:{x:aBox.x+aBox.width/2-mapBox.x+20,y:aBox.y+aBox.height/2-mapBox.y}});
    await frame.locator('.leaflet-popup').waitFor({timeout:5000});
    assert.equal(await page.evaluate(()=>mapMessages.filter(m=>m.type==='streamlit:setComponentValue').length),countBefore);
    phase='reset';await page.getByRole('button',{name:'Chọn lại',exact:true}).click();
    await frame.waitForFunction(()=>document.querySelectorAll('.point').length===0);
    assert.equal(await map.getAttribute('data-persisted'),'full_app');
    assert.equal(await page.getByTestId('stException').count(),0);
    assert.deepEqual(errors,[]);
    const report={status:'PASS',scope:'Full Streamlit app + real Leaflet click/callback loop on SYNTHETIC export',
      checks:['quality warning preserved in collapsed source details','coverage counts available on demand',
        'single click ON a road selects and displays A','next single click ON a road selects and displays B','automatic route appears',
        'two markers remain','map is not remounted when route controls change','view road popup works without Python rerun',
        'reset clears markers without remount','no Streamlit/JavaScript exception'],limits:['Synthetic graph; background tile images stubbed.']};
    fs.mkdirSync(path.dirname(reportPath),{recursive:true});fs.writeFileSync(reportPath,JSON.stringify(report,null,2)+'\n');console.log(report);
  } catch(e) {
    if(page){await page.screenshot({path:path.join(run,'failure.png'),fullPage:true}).catch(()=>{});
      fs.writeFileSync(path.join(run,'failure.txt'),await page.locator('body').innerText().catch(()=>''));
      const messages=await page.evaluate(()=>window.mapMessages||[]).catch(()=>[]);
      const frames=await Promise.all(page.frames().filter(f=>f.url().includes('portopulse_map')).map(f=>f.evaluate(()=>window.renderMessages||[]).catch(()=>[])));
      fs.writeFileSync(path.join(run,'debug.json'),JSON.stringify({phase,messages,frames,consoleMessages},null,2));}
    console.error('FAILED PHASE:',phase);throw e;
  } finally {if(browser)await browser.close();if(app)app.kill();fs.closeSync(log);}
})().catch(e=>{console.error(e);process.exitCode=1;});
