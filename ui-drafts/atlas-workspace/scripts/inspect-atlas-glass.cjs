const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { execFileSync } = require('node:child_process');
const modulesDir = process.env.ATLAS_NODE_MODULES;
const { chromium } = require(modulesDir ? path.join(modulesDir, 'playwright') : 'playwright');
const rootDir = path.resolve(__dirname, '..');
const output = path.join(rootDir, 'references');
const source = path.join(rootDir, 'atlas-conversation-workspace.html');
const preview = path.join(rootDir, 'preview', 'atlas-glass-preview.html');
const lucideUmd = process.env.ATLAS_LUCIDE_UMD || (modulesDir ? path.join(modulesDir, 'lucide/dist/umd/lucide.js') : require.resolve('lucide/dist/umd/lucide.js'));
const renderer = process.env.ATLAS_VISUALIZE_RENDERER;
const full = process.argv.includes('--verify');
let qaBrowser;

(async () => {
  const fragment = await fs.readFile(source, 'utf8');
  const scripts = [...fragment.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  scripts.forEach(match => new Function(match[1]));
  assert(!/<(?:html|head|body)[\s>]/i.test(fragment));
  assert(Buffer.byteLength(fragment) < 1000000);
  assert(renderer, 'Set ATLAS_VISUALIZE_RENDERER to the current visualize skill scripts/render.py');
  execFileSync(process.env.ATLAS_PYTHON || 'python',[renderer,source,preview,'--force'],{stdio:'pipe'});
  let previewMarkup=await fs.readFile(preview,'utf8');
  const resources=[
    ['https://unpkg.com/@floating-ui/core@1.7.3/dist/floating-ui.core.umd.min.js',path.join(rootDir,'vendor','floating-ui.core.umd.min.js')],
    ['https://unpkg.com/@floating-ui/dom@1.7.4/dist/floating-ui.dom.umd.min.js',path.join(rootDir,'vendor','floating-ui.dom.umd.min.js')],
    ['https://unpkg.com/lucide@1.17.0/dist/umd/lucide.js',lucideUmd]
  ];
  for(const [url,file] of resources)previewMarkup=previewMarkup.replace(url,'data:text/javascript;base64,'+(await fs.readFile(file)).toString('base64'));
  await fs.writeFile(preview,previewMarkup);
  const browser = await chromium.launch({headless:true,...(process.env.ATLAS_CHROMIUM_EXECUTABLE ? {executablePath:process.env.ATLAS_CHROMIUM_EXECUTABLE} : {})});
  qaBrowser=browser;
  const context = await browser.newContext({viewport:{width:1056,height:1180},colorScheme:'light',deviceScaleFactor:1,ignoreHTTPSErrors:true});
  const page = await context.newPage();
  const errors=[],consoleErrors=[],requestFailures=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
  page.on('requestfailed',request=>requestFailures.push({url:request.url(),error:request.failure()?.errorText}));
  await context.route('**/lucide@*/dist/umd/lucide.js', async route=>route.fulfill({contentType:'text/javascript',body:await fs.readFile(lucideUmd)}));
  await page.goto(pathToFileURL(preview).href,{waitUntil:'load',timeout:45000});
  const frame = page.frames().find(frame=>frame.parentFrame());
  assert(frame,'Standalone preview iframe exists');
  const root = frame.locator('#atlas-conversation-workspace');
  await root.waitFor();
  await frame.waitForFunction(()=>document.querySelectorAll('#atlas-conversation-workspace svg.lucide').length>20);
  await page.waitForTimeout(250);
  await root.screenshot({path:path.join(output,'atlas-glass-workspace.png')});
  const measurements = await frame.evaluate(()=>{
    const root=document.querySelector('#atlas-conversation-workspace');
    const bounds=root.getBoundingClientRect();
    return {root:{width:bounds.width,height:bounds.height},glass:[...root.querySelectorAll('.cw-sidebar,.cw-composer,.cw-node,.cw-inspector')].slice(0,10).map(el=>({class:el.className,filter:getComputedStyle(el).backdropFilter,background:getComputedStyle(el).backgroundColor})),pickers:[...root.querySelectorAll('[data-picker-trigger]')].map(el=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height}))};
  });
  const checks=[],layouts=[];
  if(full){
    const titles={clarify:'需求澄清',brief:'研究简报',supervisor:'研究协调器',a:'技术与产品',b:'商业与增长',c:'隐私与风险',report:'最终报告'};
    for(const [key,title] of Object.entries(titles)){
      await frame.locator('.cw-node[data-node="'+key+'"]').click();
      assert.equal(await frame.locator('[data-detail-title]').innerText(),title);
      for(const tab of ['overview','io','events']){
        await frame.locator('[data-inspector-tab="'+tab+'"]').click();
        assert(await frame.locator('[data-inspector-pane="'+tab+'"]').isVisible());
      }
      if(key==='report'){
        assert(await frame.locator('[data-events-empty]').isVisible());
        await frame.locator('[data-inspector-tab="io"]').click();
        assert.match(await frame.locator('[data-detail-output]').innerText(),/尚未执行/);
      }
    }
    checks.push('All 7 graph nodes update all 3 inspector views; pending node has no fabricated output or events');
    await frame.locator('.cw-node[data-node="b"]').click();
    await frame.locator('[data-inspector-tab="overview"]').click();
    await frame.locator('[data-inspector-tab="overview"]').press('ArrowRight');
    assert.equal(await frame.locator('[data-inspector-tab="io"]').getAttribute('aria-selected'),'true');
    await frame.locator('[data-inspector-tab="io"]').press('End');
    assert.equal(await frame.locator('[data-inspector-tab="events"]').getAttribute('aria-selected'),'true');
    await root.screenshot({path:path.join(output,'atlas-glass-inspector-events.png')});
    await frame.locator('[data-inspector-tab="events"]').press('Escape');
    assert(!(await frame.locator('.cw-inspector').isVisible()));
    assert(await frame.locator('.cw-node[data-node="b"]').evaluate(el=>el===document.activeElement));
    await frame.locator('.cw-node[data-node="b"]').press('Enter');
    assert(await frame.locator('.cw-inspector').isVisible());
    await frame.locator('[data-inspector-tab="io"]').click();
    await root.screenshot({path:path.join(output,'atlas-glass-inspector-io.png')});
    await frame.locator('[data-inspector-tab="overview"]').click();
    checks.push('Inspector keyboard tabs, Escape, focus return and reopen');
    await frame.locator('#cw-model').click();
    await frame.locator('#cw-model-menu').evaluate(async el=>{await Promise.all(el.getAnimations().map(animation=>animation.finished));});
    assert.equal(await frame.locator('#cw-model-menu').evaluate(el=>Math.round(el.getBoundingClientRect().width)),232);
    await root.screenshot({path:path.join(output,'atlas-glass-model-open.png')});
    await frame.locator('[data-model-value="qwen"]').press('ArrowDown');
    await frame.locator('[data-model-value="deepseek"]').press('Enter');
    assert.equal(await frame.locator('[data-model-label]').innerText(),'DeepSeek V3.2');
    assert.equal(await frame.locator('[data-detail-model]').innerText(),'Qwen3.5');
    await frame.locator('#cw-skill').click();
    await frame.locator('[data-skill-value="product-comparison"]').click();
    await frame.locator('#cw-skill').click();
    await frame.locator('#cw-skill-menu').evaluate(async el=>{await Promise.all(el.getAnimations().map(animation=>animation.finished));});
    await root.screenshot({path:path.join(output,'atlas-glass-skills-open.png'),animations:'disabled'});
    await frame.locator('[data-skill-value="product-comparison"]').press('Escape');
    assert.equal(await frame.locator('#cw-skill').getAttribute('aria-expanded'),'false');
    await frame.locator('#cw-model').click();
    await frame.locator('#cw-skill').click();
    assert(!(await frame.locator('#cw-model-menu').isVisible()));
    await frame.locator('[data-chat-title]').click();
    assert(!(await frame.locator('#cw-skill-menu').isVisible()));
    checks.push('Compact radio menus, keyboard selection, one open menu, Escape, outside click; current run model stays unchanged');
    await frame.locator('#cw-message').fill('请补充产品的订阅定价。');
    await frame.locator('#cw-message').dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true,bubbles:true});
    assert.equal(await frame.locator('#cw-message').inputValue(),'请补充产品的订阅定价。');
    await frame.locator('#cw-message').press('Shift+Enter');
    assert.match(await frame.locator('#cw-message').inputValue(),/\n/);
    await frame.locator('#cw-message').press('Enter');
    assert.equal(await frame.locator('#cw-message').inputValue(),'');
    assert.match(await frame.locator('[data-followup]').innerText(),/DeepSeek V3.2 · 产品对比/);
    assert.equal(await frame.locator('[data-detail-model]').innerText(),'Qwen3.5');
    checks.push('IME composition, Shift+Enter, local send and selection snapshot');
    await frame.locator('.cw-graph-toggle').click();
    assert(!(await frame.locator('.cw-graph-panel').isVisible()));
    await root.screenshot({path:path.join(output,'atlas-glass-graph-collapsed.png')});
    await frame.locator('.cw-graph-toggle').click();
    assert(await frame.locator('.cw-inspector').isVisible());
    await frame.locator('[data-action="advance"]').click();
    assert.equal(await root.getAttribute('data-stage'),'writing');
    assert.match(await frame.locator('[data-detail-tool]').innerText(),/final_report_generation/);
    await frame.locator('.cw-node[data-node="b"]').click();
    assert.equal(await frame.locator('[data-detail-status]').innerText(),'已完成');
    await frame.locator('[data-inspector-tab="io"]').click();
    assert.match(await frame.locator('[data-detail-output]').innerText(),/compressed_research/);
    assert(!/tavily_search/.test(await frame.locator('[data-detail-tool]').innerText()));
    await frame.locator('[data-action="advance"]').click();
    assert.match(await frame.locator('[data-detail-output]').innerText(),/final_report/);
    await frame.locator('.cw-new-chat').click();
    assert.equal(await root.getAttribute('data-stage'),'idle');
    assert.match(await frame.locator('[data-detail-output]').innerText(),/暂无输出/);
    await frame.locator('#cw-message').fill('研究离线搜索工具');
    await frame.locator('.cw-send').click();
    assert.equal(await root.getAttribute('data-stage'),'clarify');
    assert.equal(await frame.locator('[data-detail-model]').innerText(),'DeepSeek V3.2');
    assert.match(await frame.locator('[data-detail-input]').innerText(),/研究离线搜索工具/);
    checks.push('Graph collapse, run progression, completed researcher output, pending/new run reset and captured model');
    // The standalone host commits iframe messages asynchronously. Reload only
    // after this exact UI snapshot reaches storage, rather than racing its port.
    const savedClient=await frame.evaluate(()=>window.openai.widgetState.privateContent.client);
    await page.waitForFunction(client=>Object.keys(localStorage).some(key=>{
      if(!key.startsWith('codex:visualization-widget-state-v2:'))return false;
      const saved=JSON.parse(localStorage.getItem(key));
      return saved?.privateContent?.client?.id===client.id&&saved.privateContent.client.revision===client.revision;
    }),savedClient);
    await page.reload({waitUntil:'load'});
    const restored = page.frames().find(frame=>frame.parentFrame());
    await restored.locator('#atlas-conversation-workspace').waitFor();
    const saved = await restored.evaluate(()=>window.openai.widgetState);
    assert.equal(saved.privateContent.atlasConversation.activeThread,'draft');
    assert.equal(saved.privateContent.atlasConversation.draft.runModel,'deepseek');
    // Seed a clean representative run through the supported widget-state event.
    await restored.evaluate(()=>window.dispatchEvent(new CustomEvent('openai:set_globals',{detail:{globals:{widgetState:{privateContent:{atlasConversation:{model:'qwen',skill:'auto',graph:true,inspector:true,inspectorTab:'overview',selected:'b',activeThread:'example',draftText:'',example:{stage:'research',runModel:'qwen',runSkill:'auto',followups:[]},draft:{exists:false,title:'新研究',stage:'idle',runModel:null,runSkill:'auto',followups:[]}},design:{theme:'system',graphWidth:350,radius:14,blur:28,reflection:65}}}}}})));
    const live=restored;
    await live.locator('#cw-model').click();
    await live.locator('[data-model-value="deepseek"]').click();
    await page.waitForTimeout(100);
    const stale=await live.evaluate(()=>JSON.parse(JSON.stringify(window.openai.widgetState)));
    await live.locator('#cw-model').click();
    await live.locator('[data-model-value="gpt4o"]').click();
    await live.evaluate(snapshot=>window.dispatchEvent(new CustomEvent('openai:set_globals',{detail:{globals:{widgetState:snapshot}}})),stale);
    assert.equal(await live.locator('[data-model-label]').innerText(),'GPT-4o');
    await live.locator('#cw-model').click();
    await live.locator('[data-model-value="qwen"]').click();
    checks.push('State restoration and stale same-client revision protection');
    for(const theme of ['light','dark']){
      await page.emulateMedia({colorScheme:theme,reducedMotion:'reduce'});
      for(const width of [1440,1024,900,736,390,320]){
        await page.setViewportSize({width:width+32,height:1180});
        await page.waitForTimeout(80);
        const size=await live.evaluate(()=>{
          const root=document.querySelector('#atlas-conversation-workspace'),bounds=root.getBoundingClientRect();
          const overflow=[...root.querySelectorAll('button,textarea,pre,.cw-inspector,.cw-node,.cw-composer,.cw-detail-stats')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&(r.left<bounds.left-1||r.right>bounds.right+1);}).map(el=>el.className);
          return {rootWidth:bounds.width,overflow,filter:getComputedStyle(root.querySelector('.cw-inspector')).backdropFilter};
        });
        assert.equal(size.overflow.length,0,theme+' '+width+' overflows '+size.overflow);
        for(const picker of ['model','skill']){
          await live.locator('[data-picker-trigger="'+picker+'"]').click();
          const fit=await live.locator('[data-picker-menu="'+picker+'"]').evaluate(el=>{const r=el.getBoundingClientRect(),f=el.closest('form').getBoundingClientRect();return r.left>=f.left&&r.right<=f.right;});
          assert(fit,theme+' '+width+' '+picker+' menu stays inside composer');
          await live.locator('[data-picker-menu="'+picker+'"] [aria-checked="true"]').press('Escape');
        }
        layouts.push({theme,width,...size});
        await live.locator('[data-chat-title]').click();
        if(width===1024||width===390)await live.locator('#atlas-conversation-workspace').screenshot({path:path.join(output,`atlas-glass-${theme}-${width}.png`)});
      }
    }
    checks.push('Light/dark 1440/1024/900/736/390/320 layouts and both open menus; reduced motion');
    const touch=await browser.newContext({viewport:{width:352,height:1000},colorScheme:'light',hasTouch:true,isMobile:true,deviceScaleFactor:1});
    const touchPage=await touch.newPage();
    await touchPage.goto(pathToFileURL(preview).href,{waitUntil:'load'});
    const touchFrame=touchPage.frames().find(frame=>frame.parentFrame());
    await touchFrame.locator('#atlas-conversation-workspace').waitFor();
    for(const selector of ['#cw-model','#cw-skill','.cw-inspector-tab','.cw-send'])assert((await touchFrame.locator(selector).first().boundingBox()).height>=44);
    await touchFrame.locator('.cw-node[data-node="b"]').tap();
    await touchFrame.locator('[data-inspector-tab="io"]').tap();
    assert(await touchFrame.locator('[data-inspector-pane="io"]').isVisible());
    await touchFrame.locator('[data-detail-title]').tap();
    await touchPage.waitForTimeout(200);
    await touchFrame.locator('#atlas-conversation-workspace').screenshot({path:path.join(output,'atlas-glass-touch-320.png'),animations:'disabled'});
    await touch.close();
    checks.push('Touch targets at least 44 px; node selection and inspector tabs on a 320 px touch layout');
  }
  const report={measurements,checks,layouts,diagnostics:{errors,consoleErrors,requestFailures,iconSource:'Installed Lucide UMD and pinned Floating UI assets embedded only in the local standalone preview.'}};
  await fs.writeFile(path.join(output,'atlas-glass-verification.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report));
  await browser.close();
  assert.equal(errors.length,0,'No UI runtime errors');
  assert.equal(consoleErrors.length,0,'No browser console errors');
  assert.equal(requestFailures.length,0,'No failed preview resource requests');
  await fs.copyFile(source,path.join(rootDir,'preview','atlas-glass-workspace.html'));
})().catch(async error=>{console.error(error);if(qaBrowser)await qaBrowser.close();process.exitCode=1;});
