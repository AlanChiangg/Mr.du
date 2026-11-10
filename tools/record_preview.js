// Record a scripted interaction frame by frame on a manual clock, so the capture is smooth however slow screenshots are.
// Usage: node tools/record_preview.js OUT_DIR   then, for a GIF:
//   ffmpeg -framerate 20 -i OUT_DIR/f%04d.png -vf "fps=14,scale=500:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" preview.gif
const http = require('http'), fs = require('fs'), path = require('path');
const { chromium } = require('playwright');
const ROOT = path.resolve(__dirname, '..'), OUT = process.argv[2], W = 860, H = 700, DT = 50;
const TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.webp': 'image/webp', '.png': 'image/png', '.woff2': 'font/woff2'};
const srv = http.createServer((q, r) => {
  let p = decodeURIComponent(q.url.split('?')[0]); if (p.endsWith('/')) p += 'index.html';
  const f = path.join(ROOT, p);
  if (!f.startsWith(ROOT) || !fs.existsSync(f)) { r.writeHead(404); r.end(); return; }
  r.writeHead(200, {'content-type': TYPES[path.extname(f)] || 'application/octet-stream'}); fs.createReadStream(f).pipe(r);
});
(async () => {
  await new Promise(ok => srv.listen(0, '127.0.0.1', ok));
  const browser = await chromium.launch({args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
  const page = await browser.newPage({viewport: {width: W, height: H}, deviceScaleFactor: 1});
  await page.addInitScript(() => {
    const real = performance.now.bind(performance), rafReal = window.requestAnimationFrame.bind(window);
    let t = 0, manual = false, q = [];
    performance.now = () => manual ? t : real();
    window.requestAnimationFrame = cb => { if (!manual) return rafReal(cb); q.push(cb); return q.length; };
    window.__manual = () => { t = real(); manual = true; };
    window.__tick = dt => { t += dt; const run = q; q = []; for (const cb of run) cb(t); };
  });
  await page.goto(`http://127.0.0.1:${srv.address().port}/`, {waitUntil: 'load'});
  await page.waitForTimeout(1750);
  // a visible stand-in for the mouse cursor, which screenshots do not include
  await page.evaluate(() => {
    const c = document.createElement('div'); c.id = 'fakeCursor';
    c.style.cssText = 'position:fixed;left:-99px;top:-99px;width:26px;height:26px;z-index:99;pointer-events:none;transform:translate(-4px,-3px)';
    c.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 2l15 9-7 1.6L9 20z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    addEventListener('pointermove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('pointerdown', () => { c.style.transform = 'translate(-4px,-3px) scale(.82)'; }, true);
    addEventListener('pointerup', () => { c.style.transform = 'translate(-4px,-3px)'; }, true);
    window.__manual();
  });
  const box = await page.locator('#portrait').boundingBox();
  const P = (u, v) => [box.x + u * box.width, box.y + v * box.height];
  let n = 0, pos = [W * 0.9, H * 0.93];
  const frame = async () => { await page.evaluate(dt => window.__tick(dt), DT); await page.screenshot({path: path.join(OUT, 'f' + String(n++).padStart(4, '0') + '.png')}); };
  const hold = async ms => { for (let i = 0; i < Math.round(ms / DT); i++) await frame(); };
  const glide = async (to, ms) => { const from = pos, k = Math.max(1, Math.round(ms / DT)); for (let i = 1; i <= k; i++) { const e = i / k, s = e * e * (3 - 2 * e); pos = [from[0] + (to[0] - from[0]) * s, from[1] + (to[1] - from[1]) * s]; await page.mouse.move(pos[0], pos[1]); await frame(); } };
  await hold(350);                                   // asleep
  await glide([W * 0.86, H * 0.8], 300); await hold(700);   // the first move wakes him
  await glide([W * 0.06, H * 0.45], 1100); await hold(250); // eyes follow to the left
  await glide([W * 0.94, H * 0.5], 1300); await hold(250);  // and to the right
  await glide(P(0.67, 0.61), 500); await hold(150);
  await page.mouse.down(); await hold(100);
  await glide(P(0.93, 0.7), 450); await hold(450);          // pull the cheek out
  await glide(P(0.86, 0.38), 400); await hold(250);
  await page.mouse.up(); await hold(1500);                  // let go: it ripples back
  await glide(P(0.5, 0.56), 400); await hold(100);
  await page.mouse.down(); await hold(100);
  await glide(P(0.5, 0.86), 450); await hold(450);          // pull the nose down
  await page.mouse.up(); await hold(1600);
  console.log('frames', n);
  await browser.close(); srv.close();
})().catch(e => { console.error(e); process.exit(1); });
