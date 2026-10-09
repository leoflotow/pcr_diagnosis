/* 真实浏览器交互与尺寸检查；仅连接独立验证服务，不请求模型。 */
const {chromium}=require(process.env.BIO_PLAYWRIGHT_PATH || '../frontend/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const base=process.env.BIO_QA_URL||'http://127.0.0.1:8521';
const output=path.resolve(__dirname,'../build/qa/browser');fs.mkdirSync(output,{recursive:true});
async function post(context,url,body){const response=await context.request.post(base+'/api/v1'+url,{headers:{'X-Teaching-Request':'1'},data:body});assert(response.ok(),await response.text());return response.json()}
async function size(page,name){const measurements=await page.evaluate(()=>({width:innerWidth,body:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('button,input,textarea,.panel,nav a')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&(r.right>innerWidth+1||r.left< -1)}).map(e=>e.outerHTML.slice(0,120))}));assert(measurements.body<=measurements.width+1,JSON.stringify(measurements));assert(!measurements.overflow.length,JSON.stringify(measurements));await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});return measurements}
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});const context=await browser.newContext({viewport:{width:1366,height:900}}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));const teacher=await browser.newContext({viewport:{width:1366,height:900}});
 await post(teacher,'/session',{role:'teacher',code:process.env.BIO_QA_TEACHER_CODE||'platform-qa-only'});
 const entries=await (await teacher.request.get(base+'/api/v1/knowledge?q='+encodeURIComponent('丙酮酸'))).json();
 const task=await post(teacher,'/teacher/tasks',{title:'梯度退火实验任务',instructions:'先理解知识关联，再记录真实实验观察。',transfer_prompt:'阳性对照正常而样本无带时，还需要什么证据？',knowledge_ids:[entries.items[0].id],knowledge_note:'注意区分自动匹配与已核实关系。'});
 const measures=[];
 for(const width of [360,390,430,1366,1920]){
  await page.setViewportSize({width,height:900});await page.goto(base);await page.getByRole('heading',{name:'生物功能图谱',exact:true}).waitFor();assert.equal(await page.title(),'生物实验智学平台');await page.getByText('探索基因、蛋白与代谢物的通路关联',{exact:true}).waitFor();await page.getByText('记录实验现象，在证据与反馈中改进判断',{exact:true}).waitFor();measures.push({page:'home',...await size(page,'home-'+width)});
  await page.goto(base+'/knowledge/'+entries.items[0].id);await page.getByRole('heading',{name:entries.items[0].name,exact:true}).waitFor();measures.push({page:'knowledge',...await size(page,'knowledge-'+width)});
 }
 await page.setViewportSize({width:390,height:900});
 await page.getByRole('button',{name:'放大图谱'}).click();await page.getByRole('button',{name:'复位',exact:true}).click();
 const graphNode=page.locator('.graph-node').last();const targetName=await graphNode.getAttribute('aria-label');await graphNode.click();await page.getByRole('heading',{name:targetName,exact:true}).waitFor();
 await page.getByRole('button',{name:/^收藏 \d/}).click();
 await page.getByLabel('导入收藏文件').setInputFiles({name:'old-favorites.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify([{k:'p0',label:'旧收藏'},{id:'missing-id'}]))});
 await page.getByText(/以下词条目前无法对应/).waitFor();const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'导出收藏'}).click();const download=await downloading;await download.saveAs(path.join(output,'favorites-export.json'));const favorites=JSON.parse(fs.readFileSync(path.join(output,'favorites-export.json')));assert(favorites.items.some(e=>e.id.startsWith('prot-')));
 await page.setViewportSize({width:390,height:900});await page.goto(base+'/experiment?task='+task.code);
 await page.getByLabel('课程名称',{exact:true}).fill('分子生物学实验');await page.getByRole('button',{name:'下一步',exact:true}).click();
 await page.getByLabel('原始现象与操作记录').fill('样本未见清晰条带，尚未核对对照。');
 await page.getByLabel('电泳图（PNG／JPG，不超过10 MB，可稍后补传）').setInputFiles(path.resolve(__dirname,'../build/qa/gel.png'));
 await page.getByRole('button',{name:'下一步',exact:true}).click();await page.getByLabel('我的初步判断与依据').fill('先核对对照与模板记录，现有信息不足以确定原因。');
 await page.getByRole('link',{name:'查询相关知识'}).click();await page.getByRole('link',{name:'返回实验记录'}).click();
 await page.getByRole('button',{name:/2.*实验观察/}).click();await page.getByLabel('电泳图（PNG／JPG，不超过10 MB，可稍后补传）').setInputFiles(path.resolve(__dirname,'../build/qa/gel.png'));await page.getByRole('button',{name:/3.*参数与初判/}).click();assert((await page.getByLabel('我的初步判断与依据').inputValue()).includes('先核对对照'));
 await page.getByRole('button',{name:'下一步',exact:true}).click();await size(page,'experiment-draft-390');
 await page.getByRole('button',{name:'保存初判并查看排查建议',exact:true}).click();await page.waitForURL('**/cases/*');
 const rid=Number(page.url().split('/').pop());const code=await page.locator('.code-panel code').innerText();assert(code.length>20);
 await page.getByLabel('待验证假设',{exact:true}).fill('模板状态可能影响扩增');await page.getByLabel('拟改变的变量').fill('改用核对过的模板');await page.getByLabel('对照设置',{exact:true}).fill('设置阳性与阴性对照');await page.getByLabel('预期结果',{exact:true}).fill('与原记录比较目标条带');await page.getByLabel('不同结果怎样解释').fill('对照正常且改善支持假设，否则继续排查');await page.getByRole('button',{name:'保存验证计划',exact:true}).click();await page.getByRole('button',{name:'追加实际复测记录'}).waitFor();
 await page.getByText('设置发送区域与匿名泳道身份',{exact:true}).click();await page.getByRole('button',{name:'预览发送区域'}).click();await page.getByAltText('准备发送的处理副本').waitFor();assert(await page.getByRole('button',{name:'请求 AI 辅助观察',exact:true}).isDisabled());await size(page,'case-student-390');
 const teacherPage=await teacher.newPage();teacherPage.on('pageerror',e=>errors.push(String(e)));await teacherPage.goto(base+'/teacher');await teacherPage.getByRole('heading',{name:'课堂案例',exact:true}).waitFor();await teacherPage.getByRole('button',{name:new RegExp('#'+rid+' ·')}).click();await teacherPage.getByLabel('判断原因',{exact:true}).fill('原因待核实');await teacherPage.getByLabel('判断依据',{exact:true}).fill('先核对原始对照记录与模板状态');await teacherPage.getByRole('button',{name:'保存独立判断',exact:true}).click();await teacherPage.getByText('已保存独立判断：',{exact:false}).waitFor();await teacherPage.getByRole('button',{name:'进入常规复核并查看建议'}).click();await teacherPage.getByLabel('判断原因',{exact:true}).fill('原因待核实');await teacherPage.getByLabel('复核依据或备注',{exact:true}).first().fill('现阶段证据不足，建议补充对照');await teacherPage.getByRole('button',{name:'保存教师反馈',exact:true}).click();await teacherPage.waitForTimeout(1000);await teacherPage.screenshot({path:path.join(output,'teacher-feedback-check.png'),fullPage:true});await teacherPage.getByText(/当前版本\s*1/).waitFor();await size(teacherPage,'teacher-1366');
 await page.reload();await page.getByLabel('判断原因',{exact:true}).fill('原因待核实');await page.getByLabel('判断依据',{exact:true}).first().fill('根据教师反馈补充对照记录后再判断');await page.getByRole('button',{name:'提交对应当前反馈的修订'}).click();await page.getByText('已提交修订：',{exact:false}).waitFor();
 await page.getByLabel('实际复测时间').fill('2026-10-01T10:00');await page.getByLabel('实际改变的条件').fill('换用已核对模板');await page.getByLabel('保持一致的条件').fill('其余体系和循环一致');await page.getByLabel('对照设置',{exact:true}).last().fill('设置阳性和阴性对照');await page.getByLabel('实际样本结果').fill('仍需核对弱带');await page.getByLabel('与预期的比较').fill('尚不能确认改善');await page.getByRole('button',{name:'追加实际复测记录'}).click();await page.getByRole('heading',{name:/复测 #/}).waitFor();
 await page.getByLabel('独立判断',{exact:true}).fill('需要继续核对模板与操作记录');await page.getByLabel('判断依据',{exact:true}).fill('阳性正常只能缩小范围');await page.getByRole('button',{name:'提交独立作答原稿'}).click();await page.getByText('需要继续核对模板与操作记录',{exact:true}).waitFor();
 const report=await context.request.get(base+`/api/v1/cases/${rid}/report`);assert(report.ok());assert((await report.text()).includes('实际复测'));
 for(const width of [360,390,430,1366,1920]){await page.setViewportSize({width,height:900});measures.push({page:'case',...await size(page,'case-'+width)})}
 await teacherPage.getByRole('button',{name:'课堂任务',exact:true}).click();await teacherPage.getByRole('heading',{name:'发布课堂任务',exact:true}).waitFor();await size(teacherPage,'teacher-tasks-1366');
 await teacherPage.getByRole('button',{name:'图像评估',exact:true}).click();await teacherPage.getByRole('heading',{name:'图像辅助观察评估',exact:true}).waitFor();await size(teacherPage,'teacher-evaluation-1366');
 for(const width of [360,390,430,1366,1920]){await teacherPage.setViewportSize({width,height:900});measures.push({page:'teacher',...await size(teacherPage,'teacher-evaluation-'+width)})}
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(output,'measurements.json'),JSON.stringify({measures,errors,case_id:rid,task_code:task.code},null,2));console.log('浏览器完整教学流程与五种屏幕尺寸通过；截图位于 build/qa/browser。');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
