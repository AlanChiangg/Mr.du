// Behaviour checks: blinking, the idle acts, a click, and touch dragging on a phone.
// Usage: node tools/check_behaviour.js OUT_DIR
const http = require('http'), fs = require('fs'), path = require('path');
const { chromium, devices } = require('playwright');
const ROOT = path.resolve(__dirname, '..'), OUT = process.argv[2];
const TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.webp': 'image/webp', '.png': 'image/png', '.woff2': 'font/woff2'};
const srv = http.createServer((q, r) => {
  let p = decodeURIComponent(q.url.split('?')[0]); if (p.endsWith('/')) p += 'index.html';
  const f = path.join(ROOT, p);
  if (!f.startsWith(ROOT) || !fs.existsSync(f)) { r.writeHead(404); r.end(); return; }
  r.writeHead(200, {'content-type': TYPES[path.extname(f)] || 'application/octet-stream'}); fs.createReadStream(f).pipe(r);
});
const ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
const faces = async (page, ms) => page.evaluate(ms => new Promise(ok => { const seen = []; const t0 = performance.now(); (function tick() { const f = window.__face.state().faceB; if (seen[seen.length - 1] !== f) seen.push(f); performance.now() - t0 < ms ? requestAnimationFrame(tick) : ok(seen); })(); }), ms);
(async () => {
  await new Promise(ok => srv.listen(0, '127.0.0.1', ok));
  const url = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await chromium.launch({args: ARGS});
  const logs = [];
  const watch = page => { page.on('console', m => { if (m.type() === 'error') logs.push('error: ' + m.text()); }); page.on('pageerror', e => logs.push('pageerror: ' + e.message)); };

  // desktop
  let page = await browser.newPage({viewport: {width: 1280, height: 800}});
  watch(page); await page.goto(url, {waitUntil: 'load'}); await page.waitForTimeout(800);
  await page.mouse.move(640, 300, {steps: 5}); await page.waitForTimeout(300);
  console.log('blink over 8s  :', (await faces(page, 8000)).join(' > '));
  await page.evaluate(() => window.__face.startAct('shifty'));
  console.log('act shifty     :', (await faces(page, 2200)).join(' > '));
  await page.evaluate(() => window.__face.startAct('tug'));
  await page.waitForTimeout(1500); await page.screenshot({path: path.join(OUT, 'act_tug.png')});
  console.log('act tug        :', (await faces(page, 3600)).join(' > '), JSON.stringify(await page.evaluate(() => window.__face.state())));
  await page.evaluate(() => window.__face.startAct('doze'));
  await page.waitForTimeout(3500); await page.screenshot({path: path.join(OUT, 'act_doze.png')});
  console.log('act doze       :', (await faces(page, 4200)).join(' > '), JSON.stringify(await page.evaluate(() => window.__face.state())));
  // a quick click is a tap
  const box = await page.locator('#portrait').boundingBox();
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.3);
  console.log('after a click  :', (await faces(page, 1200)).join(' > '));
  await page.close();

  // phone with a touch screen
  const ctx = await browser.newContext({...devices['iPhone 13']});
  page = await ctx.newPage(); watch(page);
  await page.goto(url, {waitUntil: 'load'}); await page.waitForTimeout(600);
  console.log('phone asleep   :', JSON.stringify(await page.evaluate(() => window.__face.state())));
  await page.waitForTimeout(2600);
  console.log('phone auto-wake:', JSON.stringify(await page.evaluate(() => window.__face.state())));
  const b = await page.locator('#portrait').boundingBox();
  const cdp = await ctx.newCDPSession(page);
  const touch = (type, x, y) => cdp.send('Input.dispatchTouchEvent', {type, touchPoints: type === 'touchEnd' ? [] : [{x, y}]});
  const sx = b.x + b.width * 0.36, sy = b.y + b.height * 0.6;
  await touch('touchStart', sx, sy); await page.waitForTimeout(80);
  for (let i = 1; i <= 12; i++) { await touch('touchMove', sx - i * 7, sy + i * 6); await page.waitForTimeout(25); }
  await page.waitForTimeout(400);
  console.log('phone dragging :', JSON.stringify(await page.evaluate(() => window.__face.state())));
  await page.screenshot({path: path.join(OUT, 'phone_drag.png')});
  await touch('touchEnd'); await page.waitForTimeout(1600);
  console.log('phone released :', JSON.stringify(await page.evaluate(() => window.__face.state())));
  console.log('page scrolled? ', await page.evaluate(() => [scrollX, scrollY, document.documentElement.scrollWidth, innerWidth].join(',')));
  console.log(logs.length ? 'LOGS:\n' + logs.join('\n') : 'no console errors');
  await browser.close(); srv.close();
})().catch(e => { console.error(e); process.exit(1); });
