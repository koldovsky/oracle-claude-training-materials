/* Capture the actual lesson screen HTML. No live Claude or Oracle invocation. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const packagePath = process.env.PLAYWRIGHT_MODULE || path.resolve(__dirname,'../../../slides/node_modules/playwright-chromium');
const {chromium} = require(packagePath);
const work = path.resolve(process.argv[2] || path.join(__dirname,'../.rehearsal/video'));
const plan = JSON.parse(fs.readFileSync(path.join(work,'timeline.json'),'utf8'));
(async()=>{
  const browser=await chromium.launch({headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1600,height:900},deviceScaleFactor:1,reducedMotion:'reduce'});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    fs.mkdirSync(path.join(work,'screens'),{recursive:true});
    for(let i=0;i<plan.segments.length;i++){
      await page.goto(pathToFileURL(path.join(work,'screens.html')).href+'?screen='+i);
      await page.waitForFunction(()=>document.documentElement.dataset.ready==='true');
      const overflow=await page.evaluate(()=>{
        const content=document.getElementById('content');
        const code=document.querySelector('.code');
        return {bottom:content.getBoundingClientRect().bottom,clipped:code&&code.scrollHeight>code.clientHeight+2};
      });
      if(overflow.bottom>748||overflow.clipped)errors.push('Screen does not fit: '+plan.segments[i].id+' '+JSON.stringify(overflow));
      await page.screenshot({path:path.join(work,'screens',plan.segments[i].id+'.png')});
      if(i%10===0)console.log('SCREEN',i+1,'/',plan.segments.length);
    }
    if(errors.length)throw Error(errors.join('\n'));
    const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(path.join(work,file))).digest('hex');
    fs.writeFileSync(path.join(work,'screen-validation.json'),JSON.stringify({
      timelineSha256:hash('timeline.json'),htmlSha256:hash('screens.html'),
      screens:Object.fromEntries(plan.segments.map(s=>[s.id,hash('screens/'+s.id+'.png')]))
    },null,2)+'\n');
    console.log('SCREENS_READY',plan.segments.length);
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
