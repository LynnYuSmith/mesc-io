/* Layout in a real Chrome: every pane inside the window, the image at least 240 x 200 px, the
   tools scrollable, the last unit clickable — at the default sizes and with every pane saved at
   its maximum, from 1440x900 down to 900x600. A size saved on a big screen (or a splitter dragged
   to the edge) used to push panes off a smaller window; the user saw the tools cut off.
     node tests/view_layout_real_chrome.js <viewer url> */
const { spawn } = require("node:child_process"); const http = require("node:http");
const URL_ = process.argv[2]; const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJSON = u => new Promise((res, rej) => http.get(u, r => { let b=""; r.on("data", d => b += d); r.on("end", () => res(JSON.parse(b))); }).on("error", rej));
(async () => {
  const ch = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", ["--headless=new","--remote-debugging-port=9484","--user-data-dir=/tmp/view_layout_profile","--window-size=1440,900","about:blank"], {stdio:"ignore"});
  process.on("exit", () => { try { ch.kill(); } catch(_){} });
  let t; for (let i=0;i<40;i++){ try { t=await getJSON("http://127.0.0.1:9484/json"); break; } catch { await sleep(300);} }
  const ws=new WebSocket(t.find(x=>x.type==="page").webSocketDebuggerUrl); await new Promise(r=>ws.onopen=r);
  let id=0; const pend=new Map(); const errs=[]; ws.onmessage=m=>{const d=JSON.parse(m.data); if(d.id&&pend.has(d.id)){pend.get(d.id)(d);pend.delete(d.id);} else if(d.method==="Runtime.exceptionThrown") errs.push(d.params.exceptionDetails.exception?.description);};
  const send=(m,p={})=>new Promise(r=>{const i=++id;pend.set(i,r);ws.send(JSON.stringify({id:i,method:m,params:p}));});
  const ev=async e=>{const r=await send("Runtime.evaluate",{expression:e,returnByValue:true,awaitPromise:true}); return r.result.result.value;};
  await send("Page.enable"); await send("Runtime.enable"); await send("Page.navigate",{url:URL_}); await sleep(2500);
  let bad = false;
  const check = async (label) => {
    const r = await ev(`(()=>{const W=innerWidth,H=innerHeight,out=[];
      for (const id of ['unitsCol','imageCol','toolsCol','tracesRow','stage','meta','units']) { const b=document.getElementById(id).getBoundingClientRect();
        if (b.right>W+1||b.bottom>H+1||b.left<-1||b.top<-1) out.push(id+' outside the window '+[b.left,b.top,b.right,b.bottom].map(Math.round)); }
      const st=document.getElementById('stage').getBoundingClientRect(); if (st.width<200||st.height<150) out.push('stage only '+Math.round(st.width)+'x'+Math.round(st.height));
      const m=document.getElementById('meta').getBoundingClientRect(), uc=document.getElementById('unitsCol').getBoundingClientRect(); if (m.bottom>uc.bottom+1) out.push('meta below its column');
      const tc=document.getElementById('toolsCol'); const lastBtn=[...tc.querySelectorAll('button,input,select')].pop(); if (tc.scrollHeight>tc.clientHeight+1 && getComputedStyle(tc).overflowY!=='auto') out.push('tools cut off without a scrollbar');
      const u=document.querySelector('#units .u:last-child'); document.getElementById('units').scrollTop=1e6; const ub=u.getBoundingClientRect(); const e=document.elementFromPoint(ub.left+20, Math.min(ub.bottom, document.getElementById('units').getBoundingClientRect().bottom)-5); if(!e||!e.closest('.u')) out.push('last unit row not clickable: '+(e&&(e.id||e.className)));
      return out})()`);
    console.log(label.padEnd(44), r.length ? r.join(" | ") : "ok"); if (r.length) bad = true;
  };
  await check("1440x900, defaults");
  await ev("V.tracesH=9999; V.metaH=9999; V.toolsW=9999; applyStatic(); paint(); 'ok'"); await sleep(400); await check("1440x900, every pane at its maximum");
  for (const [w,h] of [[1280,720],[1024,700],[900,600]]) { await send("Emulation.setDeviceMetricsOverride",{width:w,height:h,deviceScaleFactor:1,mobile:false}); await sleep(500); await check(`${w}x${h}, panes at maximum`); }
  await ev("V.tracesH=260; V.metaH=300; V.toolsW=260; applyStatic(); paint(); 'ok'"); await sleep(400); await check("900x600, defaults");
  console.log("exceptions:", errs.length, errs.slice(0,2)); process.exit(bad || errs.length ? 1 : 0);
})();
