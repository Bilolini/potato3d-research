// Local, isolated headless browser check. Never connects to a user's browser profile.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
(async () => {
  const root = path.resolve(__dirname, '../..');
  const browser = await chromium.launch({headless:true, executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport:{width:1280,height:1060},deviceScaleFactor:1});
  const errors=[], remote=[];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    if(route.request().url().startsWith('file:') || route.request().url().startsWith('data:')) return route.continue();
    remote.push(route.request().url()); return route.abort();
  });
  await page.goto('file://'+path.join(root,'course/showcase/index.html'));
  await page.waitForSelector('body[data-ready="true"]');
  const checks=[];
  for(let c=0;c<6;c++){
    await page.selectOption('#case', String(c));
    const methods = await page.locator('#method option').evaluateAll(nodes=>nodes.map(n=>n.value));
    for(const method of methods){
      await page.selectOption('#method',method);
      await page.waitForTimeout(150);
      const state=await page.locator('#plot').evaluate(el=>({traces:el.data.length,points:el.data[2].x.length,
        errorScale:el.layout.coloraxis.cmax,canvases:el.querySelectorAll('canvas').length}));
      if(state.traces!==3 || state.points!==1800 || state.errorScale!==8 || state.canvases<1)throw Error('Invalid render state');
      checks.push({case:c,method,...state});
    }
  }
  await page.selectOption('#case','4');
  await page.click('#reset');
  await page.screenshot({path:path.join(root,'course/evidence/showcase_desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(350);
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
  await page.screenshot({path:path.join(root,'course/evidence/showcase_mobile.png'),fullPage:true});
  const result={cases:6,method_views:checks.length,checks,javascript_errors:errors,remote_requests:remote,mobile_horizontal_overflow:overflow};
  fs.writeFileSync(path.join(root,'course/evidence/showcase_browser_check.json'),JSON.stringify(result,null,2)+'\n');
  await browser.close();
  if(errors.length||remote.length||overflow)throw Error(JSON.stringify(result));
  console.log('Checked 18 offline case/method views, reset, and mobile layout');
})();
