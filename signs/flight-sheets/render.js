const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:816,height:1056},deviceScaleFactor:2});
await p.goto('file://'+process.cwd()+'/sheet.html');await p.waitForLoadState('networkidle');await p.evaluate(()=>document.fonts.ready);
await p.pdf({path:'flight-sheets.pdf',width:'8.5in',height:'11in',printBackground:true});
await p.screenshot({path:'preview-page.png'});
await p.locator('.slip').first().screenshot({path:'preview-slip.png'});await b.close()})();
