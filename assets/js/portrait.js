// ===== LIVING PORTRAIT =====
// A photo-like head on a soft sheet. The skin is a damped wave simulation on a grid; the face itself
// is one of two pictures (joyful, shocked) with a small patch laid over the eyes to move the gaze or
// lower the lids. The code only decides which picture and patch to show and makes the skin move.
(() => {
  'use strict';
  const D = window.FACE_DATA;
  const wrap = document.getElementById('portrait'), canvas = document.getElementById('faceGl');
  const fallback = document.getElementById('faceFallback'), hand = document.getElementById('faceHand');
  if (!D || !wrap || !canvas) return;
  const gl = canvas.getContext('webgl', {alpha: true, premultipliedAlpha: true, antialias: true});
  if (!gl) return;                                   // the plain picture stays
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const DIR = 'assets/face/';

  const OVER = 1.7, N = 72, M = N + 1, SPAN = OVER / N, ORIGIN = .5 - OVER / 2;
  const WOBBLE = 2.3 * 2 * Math.PI, REACH = .085 / SPAN, C = REACH * WOBBLE, GAMMA = 2 * .14 * WOBBLE, NU = .2 * C;

  const VS = `attribute vec2 a, d; attribute float s; varying vec2 vUv; varying float vS;
    uniform vec2 lean; uniform float overS;
    void main(){ vUv = a; vS = s; vec2 p = a + d + lean; gl_Position = vec4(vec2(p.x-.5, .5-p.y)*2./overS, 0., 1.); }`;
  // A face is a whole picture plus, optionally, an eye patch from the sheet. Patch and picture are both
  // sampled with the same coordinates, so the patch stretches with the skin and can never slip.
  const FS = `#ifdef GL_FRAGMENT_PRECISION_HIGH
    precision highp float;
    #else
    precision mediump float;
    #endif
    varying vec2 vUv; varying float vS;
    uniform sampler2D texJoy, texShock, texEyes;
    uniform vec4 box; uniform vec2 cellSize;
    uniform vec3 faceA, faceB;
    uniform float fade;
    vec4 face(vec3 f){
      vec4 c = f.z > .5 ? texture2D(texShock, vUv) : texture2D(texJoy, vUv);
      vec2 q = (vUv - box.xy) / (box.zw - box.xy);
      if (f.x >= 0. && q.x > 0. && q.x < 1. && q.y > 0. && q.y < 1.) {
        vec4 e = texture2D(texEyes, f.xy + q * cellSize);
        c.rgb = c.rgb * (1. - e.a) + e.rgb;
      }
      return c;
    }
    void main(){
      if(vUv.x<0.||vUv.y<0.||vUv.x>1.||vUv.y>1.){ gl_FragColor = vec4(0.); return; }
      vec4 c = mix(face(faceA), face(faceB), fade);
      if(c.a<.004){ gl_FragColor = vec4(0.); return; }
      gl_FragColor = vec4(c.rgb*vS, c.a);
    }`;
  const sh = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o); if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(o)); return o; };
  const pr = gl.createProgram();
  gl.attachShader(pr, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { console.error(gl.getProgramInfoLog(pr)); return; }
  gl.useProgram(pr);
  const U = {};
  for (const n of ['overS', 'lean', 'texJoy', 'texShock', 'texEyes', 'box', 'cellSize', 'faceA', 'faceB', 'fade']) U[n] = gl.getUniformLocation(pr, n);
  gl.uniform1f(U.overS, OVER);
  gl.uniform1i(U.texJoy, 0); gl.uniform1i(U.texShock, 1); gl.uniform1i(U.texEyes, 2);
  gl.uniform4f(U.box, D.box[0], D.box[1], D.box[2], D.box[3]);
  gl.uniform2f(U.cellSize, D.cell[0] / D.atlas[0], D.cell[1] / D.atlas[1]);

  // every face the page can show: [patch u, patch v, 0 joy | 1 shock]; u < 0 means no patch
  const FACES = {joy: [-1, 0, 0], s_21: [-1, 0, 1]};
  for (const n in D.cells) FACES[n] = [D.cells[n][0] * D.cell[0] / D.atlas[0], D.cells[n][1] * D.cell[1] / D.atlas[1], n[0] === 's' ? 1 : 0];

  // ---- the sheet: a damped wave equation on the displacement of each node ----
  const count = M * M, ux = new Float32Array(count), uy = new Float32Array(count), vx = new Float32Array(count), vy = new Float32Array(count);
  const rest = new Float32Array(count * 2), dyn = new Float32Array(count * 3);
  const sx = new Float32Array(count), sy = new Float32Array(count);
  for (let j = 0, k = 0; j < M; j++) for (let i = 0; i < M; i++) { rest[k++] = ORIGIN + i * SPAN; rest[k++] = ORIGIN + j * SPAN; }
  const idx = new Uint16Array(N * N * 6);
  for (let j = 0, k = 0; j < N; j++) for (let i = 0; i < N; i++) { const a = j * M + i, b = a + 1, c = a + M, d = c + 1; idx[k++] = a; idx[k++] = c; idx[k++] = b; idx[k++] = b; idx[k++] = c; idx[k++] = d; }
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ARRAY_BUFFER, rest, gl.STATIC_DRAW);
  const aa = gl.getAttribLocation(pr, 'a'); gl.enableVertexAttribArray(aa); gl.vertexAttribPointer(aa, 2, gl.FLOAT, false, 0, 0);
  const dynBuf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, dynBuf); gl.bufferData(gl.ARRAY_BUFFER, dyn, gl.DYNAMIC_DRAW);
  const ad = gl.getAttribLocation(pr, 'd'), as = gl.getAttribLocation(pr, 's');
  gl.enableVertexAttribArray(ad); gl.vertexAttribPointer(ad, 2, gl.FLOAT, false, 12, 0);
  gl.enableVertexAttribArray(as); gl.vertexAttribPointer(as, 1, gl.FLOAT, false, 12, 8);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer()); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
  gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); gl.clearColor(0, 0, 0, 0);

  // a handful of skin: nodes near the point follow the hand, fully at the centre
  let brush = null;
  function takeHold(u, v, radius = .22) {
    const list = [];
    for (let k = 0; k < count; k++) {
      const dx = rest[k * 2] + ux[k] - u, dy = rest[k * 2 + 1] + uy[k] - v, w = Math.exp(-(dx * dx + dy * dy) / (radius * radius));
      if (w > .02) list.push([k, w, ux[k], uy[k]]);
    }
    brush = {u, v, list, px: 0, py: 0};
  }
  // The sheet must never fold over itself: overlapping triangles draw as a comb of cuts.
  // Every frame, whatever the physics did, each row and column is forced back into order
  // with a minimum gap between neighbours, so the picture can squash but never cross.
  const GAP = SPAN * .34, lineA = new Float32Array(M), lineB = new Float32Array(M), lineP = new Float32Array(M);
  function order(start, stride, field, base) {
    for (let i = 0; i < M; i++) { const k = start + i * stride; lineP[i] = base[k] + field[k]; }
    lineA[0] = lineP[0]; for (let i = 1; i < M; i++) lineA[i] = Math.max(lineP[i], lineA[i - 1] + GAP);
    lineB[N] = lineP[N]; for (let i = N - 1; i >= 0; i--) lineB[i] = Math.min(lineP[i], lineB[i + 1] - GAP);
    for (let i = 0; i < M; i++) { const k = start + i * stride; field[k] = (lineA[i] + lineB[i]) / 2 - base[k]; }
  }
  const restX = new Float32Array(count), restY = new Float32Array(count);
  for (let k = 0; k < count; k++) { restX[k] = rest[k * 2]; restY[k] = rest[k * 2 + 1]; }
  function untangle() {
    for (let pass = 0; pass < 2; pass++) {
      for (let j = 0; j < M; j++) order(j * M, 1, sx, restX);
      for (let i = 0; i < M; i++) order(i, M, sy, restY);
    }
  }

  // physics runs at a fixed step whatever the frame rate, otherwise it tears into spikes on large screens
  const H = 1 / 240; let simLeft = 0;
  function step(dt) {
    const c2 = C * C, wo2 = WOBBLE * WOBBLE;
    for (let j = 1; j < N; j++) for (let i = 1; i < N; i++) {
      const k = j * M + i, l = k - 1, r = k + 1, t = k - M, b = k + M;
      const lx = ux[l] + ux[r] + ux[t] + ux[b] - 4 * ux[k], ly = uy[l] + uy[r] + uy[t] + uy[b] - 4 * uy[k];
      const lvx = vx[l] + vx[r] + vx[t] + vx[b] - 4 * vx[k], lvy = vy[l] + vy[r] + vy[t] + vy[b] - 4 * vy[k];
      vx[k] += (c2 * lx - wo2 * ux[k] - GAMMA * vx[k] + NU * lvx) * dt;
      vy[k] += (c2 * ly - wo2 * uy[k] - GAMMA * vy[k] + NU * lvy) * dt;
    }
    if (brush) for (const [k, w, u0, v0] of brush.list) {
      const K = 3000 * w, Dm = 90 * w;
      vx[k] += ((u0 + brush.px * w - ux[k]) * K - vx[k] * Dm) * dt;
      vy[k] += ((v0 + brush.py * w - uy[k]) * K - vy[k] * Dm) * dt;
    }
    for (let k = 0; k < count; k++) { ux[k] += vx[k] * dt; uy[k] += vy[k] * dt; }
  }
  // a shove from nowhere: a tap, a jolt awake
  function poke(u, v, dx, dy, radius = .09) {
    for (let k = 0; k < count; k++) {
      const ax = rest[k * 2] - u, ay = rest[k * 2 + 1] - v, w = Math.exp(-(ax * ax + ay * ay) / (radius * radius));
      vx[k] += dx * w; vy[k] += dy * w;
    }
  }

  // ---- pictures ----
  const have = {joy: false, shock: false, eyes: false};
  const UNIT = {joy: 0, shock: 1, eyes: 2};
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  const load = name => new Promise(res => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = DIR + name + '.webp'; });
  function upload(name, img) {
    gl.activeTexture(gl.TEXTURE0 + UNIT[name]); gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    have[name] = true;
  }
  const avail = n => { const f = FACES[n]; return !!f && have[f[2] ? 'shock' : 'joy'] && (f[0] < 0 || have.eyes); };
  let alphaMap = null;
  function hitMap(img) {
    const a = document.createElement('canvas'); a.width = a.height = 128;
    const ac = a.getContext('2d', {willReadFrequently: true}); ac.drawImage(img, 0, 0, 128, 128);
    alphaMap = ac.getImageData(0, 0, 128, 128).data;
  }

  // ---- what he does ----
  const EYE_V = D.eyeV, CHEEK = [.68, .6];
  // [face or eye state, crossfade ms, hold ms, extras]; 'eye:k' looks sideways by k steps (-4..4)
  const ACTS = {
    shifty: [['eye:-4', 60, 520], ['eye:4', 60, 600], ['eye:-4', 60, 400], ['eye:0', 60, 260]],
    doze: [['half', 450, 700, {lean: [.006, .006]}], ['closed', 320, 500, {lean: [.012, .012]}], ['half', 200, 340],
      ['closed', 400, 1100, {lean: [.02, .02]}], ['closed', 260, 3400, {lean: [.03, .03]}], ['shock', 50, 650, {jolt: [.5, .5, 0, -.9, .3]}]],
    tug: 'tug'
  };
  const ROTATION = ['shifty', 'tug', 'doze'];

  // state
  let ready = false, tStart = 0, last = performance.now();
  let pu = .5, pv = .5, onHead = false;
  let lastInput = -1e9, awake = false, wakeDue = false, pressed = false, downAt = 0, downU = 0, downV = 0, lastX = 0, lastY = 0;
  const NAP = 1500;        // ms he is left asleep after appearing, however early the first move comes
  let moodUntil = 0;
  let act = null, actI = 0, actT = 0, rotation = [], nextIdle = 30000;
  let faceA = 'joy', faceB = 'joy', fadeT = 0, fadeMs = 1;
  let logical = 'rest', logicalMs = 70, wantEyes = null;
  let gazeK = 0, gazeX = 2, gazeY = 1;
  let nextBlink = 0, blinkStep = -1, blinkT = 0, lids = null;
  let leanX = 0, leanY = 0, lvX = 0, lvY = 0, wantLean = [0, 0];
  let handHeld = false, handGrip = false, handFrom = [1.4, .9], handTo = [1.4, .9], moveT = 0, moveMs = 1;

  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const setFace = (n, ms) => { logical = n; logicalMs = ms; };
  // one face on screen at a time; a change is a crossfade of 70ms at most
  function show(n, ms, now) {
    if (!avail(n) || n === faceB) return;
    faceA = (now - fadeT) / fadeMs > .5 ? faceB : faceA; faceB = n; fadeT = now; fadeMs = Math.min(70, Math.max(1, ms));
  }
  const joyGaze = k => k === 0 ? 'joy' : (k < 0 ? 'joy_l' : 'joy_r') + Math.abs(k);

  function startAct(name, now) {
    endAct();
    act = ACTS[name] === 'tug' ? tugAct() : ACTS[name];
    actI = -1; actT = now; advance(now);
  }
  function endAct() {
    if (act) setFace('rest', 110);
    act = null; wantEyes = null; wantLean = [0, 0]; hand.style.opacity = 0;
    if (handHeld) { handHeld = false; brush = null; }
    handGrip = false;
  }
  function advance(now) {
    actI++;
    if (!act || actI >= act.length) { endAct(); return; }
    const [what, fade, , x] = act[actI]; actT = now;
    if (what.startsWith('eye:')) { setFace('rest', fade); wantEyes = +what.slice(4); }
    else if (what === 'half' || what === 'closed') { setFace('rest', fade); wantEyes = what; }
    else { wantEyes = null; setFace(what, fade); }
    wantLean = (x && x.lean) || [0, 0];
    if (x && x.jolt) poke(...x.jolt);
    if (x && x.call) x.call(now);
  }
  const place = (el, u, v) => { el.style.left = ((u - .5) * 100 + 50) + '%'; el.style.top = ((v - .5) * 100 + 50) + '%'; };
  const moveHand = (u, v, ms) => now => { handFrom = handTo; handTo = [u, v]; moveT = now; moveMs = ms; };
  // a ghost hand reaches in from the side and tugs his cheek
  function tugAct() {
    handFrom = handTo = [1.3, .86]; hand.style.opacity = 1; hand.classList.remove('shut');
    const g = (u, v, ms, face, grip) => [face, 90, ms, {call: now => { moveHand(u, v, ms * .8)(now); handGrip = grip; }}];
    return [g(...CHEEK, 760, 'eye:4', false), g(...CHEEK, 240, 'shock', 'on'),
      g(.95, .5, 620, 'shock', 'pull'), g(.86, .56, 240, 'shock', 'pull'), g(.98, .48, 240, 'shock', 'pull'), g(.9, .52, 260, 'shock', 'pull'),
      g(1.4, .22, 900, 'shock', 'off'), ['rest', 110, 200]];
  }

  // ---- input ----
  const toUv = (x, y) => { const r = canvas.getBoundingClientRect(); return [((x - r.left) / r.width - .5) * OVER + .5, ((y - r.top) / r.height - .5) * OVER + .5]; };
  const solid = (u, v) => alphaMap && u >= 0 && v >= 0 && u < 1 && v < 1 && alphaMap[((v * 128 | 0) * 128 + (u * 128 | 0)) * 4 + 3] > 40;
  function wake(now) {
    lastInput = now;
    nextIdle = 30000 + Math.random() * 15000;
    if (awake) return;
    // browsers report the resting cursor the moment the page appears; let him be seen asleep first
    if (!ready || now < tStart + NAP) { wakeDue = true; return; }
    wakeDue = false; awake = true; nextBlink = now + 1600; lids = 'half'; setTimeout(() => { lids = null; }, 110);
  }

  addEventListener('pointermove', e => {
    const now = performance.now();
    const dx = e.clientX - lastX, dy = e.clientY - lastY; lastX = e.clientX; lastY = e.clientY;
    [pu, pv] = toUv(e.clientX, e.clientY);
    wake(now);
    if (act && !pressed) { if (act === ACTS.doze && actI < act.length - 1) { actI = act.length - 2; advance(now); } else if (act !== ACTS.doze) endAct(); }
    onHead = solid(pu, pv);
    wrap.style.cursor = pressed ? 'grabbing' : onHead ? 'grab' : '';
    // a cursor on the skin rubs it along
    if (onHead && !pressed && e.pointerType === 'mouse') poke(pu, pv, dx * .00035, dy * .00035, .07);
    if (pressed && brush) {
      let px = pu - brush.u, py = pv - brush.v; const L = Math.hypot(px, py), lim = .24;
      if (L > 0) { const k = lim * (1 - Math.exp(-L / lim)) / L; px *= k; py *= k; }   // the pull tails off so the sheet cannot fold
      brush.px = px; brush.py = py;
    }
  });
  // a touch anywhere is something to look at, even before the finger moves
  addEventListener('pointerdown', e => { lastX = e.clientX; lastY = e.clientY; [pu, pv] = toUv(e.clientX, e.clientY); wake(performance.now()); });
  wrap.addEventListener('pointerdown', e => {
    const now = performance.now(), [u, v] = toUv(e.clientX, e.clientY);
    if (!solid(u, v)) return;
    endAct(); pressed = true; downAt = now; downU = u; downV = v; takeHold(u, v);
    moodUntil = 0; wrap.style.cursor = 'grabbing';
    try { wrap.setPointerCapture(e.pointerId); } catch (_) {}
    e.preventDefault();
  });
  function release() {
    if (!pressed) return;
    const now = performance.now(), L = brush ? Math.hypot(brush.px, brush.py) : 0, held = now - downAt;
    pressed = false; brush = null; wrap.style.cursor = onHead ? 'grab' : '';
    if (L < .03 && held < 380) { moodUntil = now + 650; poke(downU, downV, 0, .5, .06); return; }   // a tap startles him
    moodUntil = now + 380 + L * 2200;                // the harder the pull, the longer he stays shocked
  }
  addEventListener('pointerup', release); addEventListener('pointercancel', release);
  addEventListener('blur', release);

  let visible = true;
  new IntersectionObserver(es => { visible = es[0].isIntersecting; }, {threshold: 0}).observe(canvas);
  new ResizeObserver(() => { const r = Math.min(devicePixelRatio || 1, 2), b = canvas.getBoundingClientRect(); canvas.width = Math.max(1, b.width * r); canvas.height = Math.max(1, b.height * r); gl.viewport(0, 0, canvas.width, canvas.height); }).observe(canvas);

  // ---- frame ----
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(.04, (now - last) / 1000); last = now;
    if (!ready || !visible) return;

    if (wakeDue && now >= tStart + NAP) wake(now);

    // acts when the page goes quiet
    if (act) { if (now - actT > act[actI][2]) advance(now); }
    else if (!reduced && !pressed && now - Math.max(lastInput, tStart) > nextIdle) {
      if (!rotation.length) rotation = [...ROTATION];
      if (!awake) wake(now);
      startAct(rotation.shift(), now); lastInput = now; nextIdle = 30000 + Math.random() * 15000;
    }

    // the ghost hand
    const mk = Math.min(1, (now - moveT) / moveMs), me = mk * mk * (3 - 2 * mk);
    const hp = [handFrom[0] + (handTo[0] - handFrom[0]) * me, handFrom[1] + (handTo[1] - handFrom[1]) * me];
    place(hand, hp[0], hp[1]);
    if (handGrip === 'on' && !handHeld) { takeHold(hp[0], hp[1], .22); handHeld = true; hand.classList.add('shut'); handGrip = 'pull'; }
    if (handHeld && brush) { brush.px = hp[0] - brush.u; brush.py = hp[1] - brush.v; }
    if (handGrip === 'off' && handHeld) { handHeld = false; brush = null; hand.classList.remove('shut'); handGrip = false; }

    // which expression
    if (!act) setFace(pressed || now < moodUntil ? 'shock' : 'rest', pressed ? 90 : 110);

    // where he is looking: the eye patch follows the cursor in steps, with a little slack so it does not chatter
    const tx = (handHeld ? hp[0] : pu) - .5, ty = (handHeld ? hp[1] : pv) - EYE_V;
    if (logical === 'shock' && avail('s_21')) {
      const fx = 2 + 2 * clamp(tx / .4, -1, 1), fy = 1 + clamp(ty / .3, -1, 1);
      if (Math.abs(fx - gazeX) > .62) gazeX = Math.round(fx);
      if (Math.abs(fy - gazeY) > .62) gazeY = Math.round(fy);
      show('s_' + gazeX + gazeY, logicalMs, now);
    } else {
      let name;
      if (wantEyes === 'half' || wantEyes === 'closed') name = 'joy_' + wantEyes;
      else if (wantEyes !== null) name = joyGaze(wantEyes);
      else if (!awake) name = 'joy_closed';
      else if (lids) name = 'joy_' + lids;
      else {
        if (blinkStep >= 0) { const s = (now - blinkT) / 62 | 0; blinkStep = s > 2 ? -1 : s; }
        else if (now > nextBlink) { blinkStep = 0; blinkT = now; nextBlink = now + 2200 + Math.random() * 3400; }
        const fk = 4 * clamp(tx / .42, -1, 1);
        if (Math.abs(fk - gazeK) > .62) gazeK = Math.round(fk);
        name = blinkStep === 1 ? 'joy_closed' : blinkStep >= 0 ? 'joy_half' : joyGaze(gazeK);
      }
      const lidMove = name === 'joy_half' || name === 'joy_closed' || faceB === 'joy_half' || faceB === 'joy_closed';
      show(name, logical === 'rest' && FACES[faceB][2] ? logicalMs : !awake ? 200 : lidMove ? 20 : 50, now);
    }

    // the head leans toward the pull, the cursor, and whatever the act asks
    const lx = (pressed || handHeld ? (brush ? brush.px * .16 : 0) : awake ? (pu - .5) * .012 : 0) + wantLean[0] + Math.sin(now * .0009) * .0015;
    const ly = (pressed || handHeld ? (brush ? brush.py * .16 : 0) : awake ? (pv - EYE_V) * .008 : 0) + wantLean[1] + Math.sin(now * .0013) * .0022;
    lvX += ((lx - leanX) * 70 - lvX * 8) * dt; lvY += ((ly - leanY) * 70 - lvY * 8) * dt;
    leanX += lvX * dt; leanY += lvY * dt;

    // skin
    simLeft += dt;
    let steps = 0;
    while (simLeft >= H && steps < 9) { step(H); simLeft -= H; steps++; }
    if (steps === 9) simLeft = 0;
    for (let j = 0; j < M; j++) for (let i = 0; i < M; i++) {
      const k = j * M + i, edge = i === 0 || j === 0 || i === N || j === N;
      sx[k] = edge ? ux[k] : (ux[k] * 4 + ux[k - 1] + ux[k + 1] + ux[k - M] + ux[k + M]) / 8;
      sy[k] = edge ? uy[k] : (uy[k] * 4 + uy[k - 1] + uy[k + 1] + uy[k - M] + uy[k + M]) / 8;
    }
    untangle();
    for (let k = 0, o = 0; k < count; k++) {
      dyn[o++] = sx[k]; dyn[o++] = sy[k];
      const r = k % M, c = k / M | 0;
      let shade = 1;      // stretched skin goes a touch lighter, squeezed skin darker
      if (r > 0 && r < N && c > 0 && c < N) shade = Math.max(.86, Math.min(1.16, 1 - ((sx[k + 1] - sx[k - 1]) + (sy[k + M] - sy[k - M])) * 1.8));
      dyn[o++] = shade;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, dynBuf); gl.bufferSubData(gl.ARRAY_BUFFER, 0, dyn);

    gl.clear(gl.COLOR_BUFFER_BIT);
    const fa = FACES[faceA], fb = FACES[faceB];
    gl.uniform3f(U.faceA, fa[0], fa[1], fa[2]); gl.uniform3f(U.faceB, fb[0], fb[1], fb[2]);
    gl.uniform1f(U.fade, Math.min(1, (now - fadeT) / fadeMs));
    gl.uniform2f(U.lean, leanX, leanY);
    gl.drawElements(gl.TRIANGLES, idx.length, gl.UNSIGNED_SHORT, 0);
  }

  (async () => {
    const shockReady = load('shock').then(img => { if (img) upload('shock', img); });
    const [base, eyes] = await Promise.all([load('joy'), load('eyes')]);
    if (!base) return;
    upload('joy', base); hitMap(base);
    if (eyes) upload('eyes', eyes);
    ready = true; tStart = performance.now();
    if (tStart < 1400 && avail('joy_closed')) {
      faceA = faceB = 'joy_closed';                                   // he starts asleep; the first move wakes him
      setTimeout(() => { if (!awake) wake(performance.now()); }, 3200);   // nobody moved (a phone, say): wake up anyway
    } else { awake = true; nextBlink = tStart + 1600; }               // the plain picture was already showing with open eyes
    requestAnimationFrame(frame);
    requestAnimationFrame(() => { fallback.style.visibility = 'hidden'; });
    await shockReady;
  })();

  // a small window into the engine, for checking it from the console or a test
  window.__face = {state: () => ({ready, awake, faceA, faceB, logical, pressed, act: act ? actI : null, have: {...have}}), startAct: n => startAct(n, performance.now())};
})();
