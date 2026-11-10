// Load the page in headless Chromium, drive it with a real pointer and save screenshots.
// Usage: node tools/check_page.js OUT_DIR [WIDTH HEIGHT]     (Playwright must be installed)
const http = require('http'), fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..'), OUT = process.argv[2] || '.', W = +(process.argv[3] || 1440), H = +(process.argv[4] || 900);
const TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.webp': 'image/webp', '.png': 'image/png', '.woff2': 'font/woff2'};
const srv = http.createServer((q, r) => {
  let p = decodeURIComponent(q.url.split('?')[0]); if (p.endsWith('/')) p += 'index.html';
  const f = path.join(ROOT, p);
  if (!f.startsWith(ROOT) || !fs.existsSync(f)) { r.writeHead(404); r.end(); return; }
  r.writeHead(200, {'content-type': TYPES[path.extname(f)] || 'application/octet-stream'}); fs.createReadStream(f).pipe(r);
});
(async () => {
  await new Promise(ok => srv.listen(0, '127.0.0.1', ok));
  const url = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await chromium.launch({args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
  const page = await browser.newPage({viewport: {width: W, height: H}, deviceScaleFactor: 1});
  const logs = [];
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') logs.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', e => logs.push('pageerror: ' + e.message));
  page.on('requestfailed', q => logs.push('requestfailed: ' + q.url()));
  await page.goto(url, {waitUntil: 'load'});
  const shot = async n => page.screenshot({path: path.join(OUT, n + '.png')});
  const st = async () => JSON.stringify(await page.evaluate(() => window.__face ? window.__face.state() : 'no engine'));
  await page.waitForTimeout(1500);
  console.log('after load   ', await st()); await shot('1_asleep');
  const box = await page.locator('#portrait').boundingBox();
  const at = (u, v) => [box.x + u * box.width, box.y + v * box.height];
  await page.mouse.move(W * 0.08, H * 0.5, {steps: 8}); await page.waitForTimeout(500);
  console.log('cursor left  ', await st()); await shot('2_look_left');
  await page.mouse.move(W * 0.92, H * 0.5, {steps: 12}); await page.waitForTimeout(500);
  console.log('cursor right ', await st()); await shot('3_look_right');
  const [cx, cy] = at(0.67, 0.6);
  await page.mouse.move(cx, cy, {steps: 10}); await page.waitForTimeout(200);
  await page.mouse.down(); await page.waitForTimeout(120);
  await page.mouse.move(cx + box.width * 0.2, cy + box.height * 0.06, {steps: 14}); await page.waitForTimeout(500);
  console.log('pulling cheek', await st()); await shot('4_pull');
  await page.mouse.up(); await page.waitForTimeout(90);
  console.log('just released', await st()); await shot('5_released');
  await page.waitForTimeout(1800);
  console.log('settled      ', await st()); await shot('6_settled');
  console.log('portrait box', JSON.stringify(box));
  console.log(logs.length ? 'LOGS:\n' + logs.join('\n') : 'no console errors');
  await browser.close(); srv.close();
})().catch(e => { console.error(e); process.exit(1); });
