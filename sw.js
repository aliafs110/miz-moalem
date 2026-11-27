// Offline-first: the app opens instantly from the phone's cache, even without VPN or internet.
// New versions are downloaded quietly in the background and used on the next open.
const C="teacher-v7";
const FILES=["./","index.html","manifest.json","apple-touch-icon.png","icon-192.png","icon-512.png","news.json"];
self.addEventListener("install",e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(FILES)).catch(()=>{}));self.skipWaiting()});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x)))));self.clients.claim()});
function timeout(ms){return new Promise((_,rej)=>setTimeout(()=>rej(new Error("timeout")),ms));}
function store(req,res){ if(res && res.ok){ const cp=res.clone(); caches.open(C).then(c=>c.put(req,cp)).catch(()=>{}); } return res; }
self.addEventListener("fetch",e=>{
  const req=e.request; if(req.method!=="GET") return;
  const url=new URL(req.url);
  if(url.origin!==location.origin) return; // fonts etc.: let the browser handle (page works without them)
  if(url.pathname.endsWith("news.json")){
    // news: try internet for 4 seconds, otherwise show the last saved news
    e.respondWith(Promise.race([fetch(req,{cache:"no-store"}).then(r=>store(req,r)),timeout(4000)]).catch(()=>caches.match(req,{ignoreSearch:true})));
    return;
  }
  const key = req.mode==="navigate" ? "index.html" : req;
  e.respondWith(caches.match(key,{ignoreSearch:true}).then(cached=>{
    const net = fetch(req).then(r=>store(key,r)).catch(()=>null);
    if(cached){ e.waitUntil(net); return cached; }
    return Promise.race([net,timeout(8000)]).then(r=>r||caches.match("index.html")).catch(()=>caches.match("index.html"));
  }));
});
