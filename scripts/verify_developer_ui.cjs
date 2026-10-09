/* 调试页真实浏览器验收；只连接独立库，不请求模型、不保存规则。 */
const {chromium}=require('../frontend/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const out=path.resolve(__dirname,'../build/qa/developer/browser');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage();const errors=[],measurements=[];
 page.on('pageerror',error=>errors.push(String(error)));
 for(const width of [360,390,732,1366]){
  await page.setViewportSize({width,height:884});await page.goto('http://127.0.0.1:8523/');
  await page.getByRole('link',{name:'开发调试',exact:true}).click();
  await page.getByRole('heading',{name:'开发访问验证'}).waitFor();
  await page.getByLabel('开发访问码',{exact:true}).fill('dev-ui-qa-only');
  await page.getByRole('button',{name:'进入开发调试',exact:true}).click();
  await page.getByRole('heading',{name:'规则库查看与校验'}).waitFor();
  await page.getByText('添加新规则',{exact:true}).click();
  const measure=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
   overflow:[...document.querySelectorAll('.panel,input,textarea,button')].filter(e=>{let r=e.getBoundingClientRect();return r.width&& (r.right>innerWidth+1||r.left< -1)}).map(e=>e.tagName)}));
  assert(measure.scroll<=width+1,JSON.stringify(measure));assert.equal(measure.overflow.length,0,JSON.stringify(measure));measurements.push(measure);
  await page.screenshot({path:path.join(out,'console-'+width+'.png'),fullPage:true});
  const request=page.waitForRequest(r=>r.url().endsWith('/api/v1/logout'));
  await page.getByRole('button',{name:'退出开发调试'}).click();assert.equal((await request).method(),'POST');
  await page.getByRole('heading',{name:'开发访问验证'}).waitFor();
  await page.getByText('已退出开发调试',{exact:true}).waitFor();
 }
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'measurements.json'),JSON.stringify({measurements,errors},null,2));
 await page.goto('http://127.0.0.1:8523/');await page.getByRole('link',{name:'开发调试',exact:true}).scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(out,'footer.png')});
 await browser.close();console.log('调试页入口、访问验证、退出POST、四种宽度与截图通过；未请求模型或写规则。');
})().catch(error=>{console.error(error);process.exit(1)});
