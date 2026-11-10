#!/usr/bin/env python3
"""Build every portrait frame from the two source expressions.

Inputs  (tools/src):   joy.png and shocked.png, each a head on a plain studio backdrop.
Outputs (assets/face): WebP frames at two sizes, all pixel-aligned on one square canvas.

  joy                 resting face, eyes straight ahead
  joy_l1..l4 / r1..r4 the same face with the irises moved left / right in four steps
  joy_half, joy_closed  eyelids half and fully lowered (blink, waking up, dozing)
  s_XY                shocked face, iris column X (0..4, left to right) and row Y (0..2, up to down);
                      s_21 looks straight ahead

Every frame of one expression is derived from the same picture, so only the eyes differ between
them and nothing else can flicker when the page swaps pictures.

Run with the image tools installed:  python tools/build_faces.py [--debug DIR]
"""
import argparse
import json
import os

import cv2
import numpy as np

from facekit import (apply_affine, bust_mask, compose_affine, load_rgb, matte, on_dark, save_rgb, warp_rgba)

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = json.load(open(os.path.join(HERE, 'geometry.json')))
CW = GEO['canvas']
LUMW = np.array([0.299, 0.587, 0.114], np.float32)

JOY_STEP = 2.25                      # canvas px of iris travel per gaze step (4 steps each way)
SHOCK_DX, SHOCK_DY = 4.5, 4.0        # canvas px per column / row of the shocked gaze grid


# ---------------------------------------------------------------- canvas

def canvases():
    """Cut both heads out, align the shocked one to the joyful one and place them on the canvas."""
    sc = GEO['scale']
    mx, my = GEO['joy']['eye_mid_src']
    t_joy = np.array([[sc, 0, CW / 2 - sc * mx], [0, sc, CW * GEO['eye_v'] - sc * my]])
    b = GEO['bust']
    fade = bust_mask(CW, CW / 2, b['cy'], b['rx'], b['ry'])
    out = {}
    for name, m in (('joy', t_joy), ('shocked', compose_affine(t_joy, np.array(GEO['shocked']['to_joy'])))):
        img = load_rgb(os.path.join(HERE, 'src', name + '.png'))
        alpha, fg, _ = matte(img, hair_y_max=GEO[name]['hair_y_max_src'])
        rgba = warp_rgba(fg, alpha, m, CW)
        rgba[..., 3] *= fade
        out[name] = rgba
    return out


def sample(img, x, y):
    return cv2.remap(img, np.float32(x), np.float32(y), cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def smooth01(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- joy: narrow smiling eyes

def robust_poly(x, y, deg=3, rounds=4, tol=1.6):
    w = np.ones_like(x)
    p = np.polyfit(x, y, deg)
    for _ in range(rounds):
        res = np.abs(np.polyval(p, x) - y)
        w = (res < max(tol, 1.5 * np.median(res))).astype(float)
        if w.sum() < deg + 3:
            break
        p = np.polyfit(x[w > 0], y[w > 0], deg)
    return p


def joy_eye_curves(rgb, eye):
    """Trace the dark band of a smiling eye: top of the lash line, top of the eyeball, lower lid."""
    cx, cy, r = eye['iris']
    lum = cv2.GaussianBlur(rgb @ LUMW, (0, 0), 0.8)
    chroma = cv2.GaussianBlur(rgb[..., 0] - rgb[..., 2], (0, 0), 0.8)
    xs = np.arange(eye['xa'], eye['xb'] + 0.01, 1.0)
    ys = np.arange(cy - 16, cy + 18, 0.25)
    top, bot, ball = [], [], []
    for x in xs:
        xx = np.full((len(ys), 1), x)
        p = sample(lum, xx, ys[:, None])[:, 0]
        c = sample(chroma, xx, ys[:, None])[:, 0]
        g = np.gradient(p, 0.25)
        kd = int(np.argmin(p))
        kt = int(np.argmin(g[:kd + 1])) if kd > 0 else 0
        kb = kd + int(np.argmax(g[kd:]))
        top.append(ys[kt]); bot.append(ys[kb])
        # over the iris the lash line is warm and the iris neutral: that colour change is the lid edge
        if abs(x - cx) < r - 4:
            below = np.nonzero(c[kt:] < 0.07)[0]
            ball.append(ys[kt + below[0]] - ys[kt] if len(below) else np.nan)
    p_top = robust_poly(xs, np.array(top))
    p_bot = robust_poly(xs, np.array(bot))
    lash = float(np.nanmedian(ball))
    return dict(p_top=p_top, p_bot=p_bot, lash=lash, xa=eye['xa'], xb=eye['xb'], iris=eye['iris'])


def joy_lids(cv, x):
    """Eyeball top and bottom at column x, never crossing."""
    y_top = np.polyval(cv['p_top'], x)
    y_bot = np.polyval(cv['p_bot'], x)
    y_u = np.minimum(y_top + cv['lash'], y_bot - 1.0)
    return y_top, y_u, y_bot


def joy_gaze_maps(cv, dx, shape):
    """Slide the iris sideways inside the slit; the whites stretch on one side and squeeze on the other."""
    h, w = shape
    cx, cy, r = cv['iris']
    xa, xb = cv['xa'], cv['xb']
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    mapx, mapy = xx.copy(), yy.copy()
    x0, x1 = int(xa) - 2, int(xb) + 3
    y0, y1 = int(cy) - 26, int(cy) + 26
    X = xx[y0:y1, x0:x1].astype(np.float64); Y = yy[y0:y1, x0:x1].astype(np.float64)

    def weight(x):      # 1 across the iris, easing to 0 at the two corners of the eye
        left = smooth01((x - xa) / max(cx - r - 1.5 - xa, 1e-3))
        right = smooth01((xb - x) / max(xb - (cx + r + 1.5), 1e-3))
        return np.where(x < cx, left, right)

    xs = X.copy()
    for _ in range(8):                                  # invert x' = x + dx * weight(x)
        xs = X - dx * weight(xs)
    _, yu_d, yb_d = joy_lids(cv, X)
    _, yu_s, yb_s = joy_lids(cv, xs)
    t = (Y - yu_d) / np.maximum(yb_d - yu_d, 1.0)       # position between the lids, kept through the move
    ys = yu_s + t * np.maximum(yb_s - yu_s, 1.0)
    # full strength between the lids, fading out over two pixels above and below
    m = smooth01((Y - (yu_d - 2.5)) / 2.0) * smooth01(((yb_d + 2.5) - Y) / 2.0)
    m *= smooth01((X - xa) / 3.0) * smooth01((xb - X) / 3.0)
    mapx[y0:y1, x0:x1] = X + m * (xs - X)
    mapy[y0:y1, x0:x1] = Y + m * (ys - Y)
    return mapx, mapy


def joy_blink_maps(cv, amount, shape):
    """Lower the upper lid by `amount` (0..1) of the opening; the lash line rides down, the lid skin stretches.

    Past the corners the dark tail of the lash line is thinned the same way, so the closed line runs
    on smoothly instead of stepping where the opening ends.
    """
    h, w = shape
    cx, cy, r = cv['iris']
    xa, xb = cv['xa'], cv['xb']
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    mapy = yy.copy()
    x0, x1 = int(xa) - 14, int(xb) + 15
    y0, y1 = int(cy) - 44, int(cy) + 24
    X = xx[y0:y1, x0:x1].astype(np.float64); Y = yy[y0:y1, x0:x1].astype(np.float64)
    xc = np.clip(X, xa, xb)                              # the fitted curves hold their end values outside
    y_top = np.polyval(cv['p_top'], xc)
    y_bot = np.polyval(cv['p_bot'], xc)
    y_u = y_top + cv['lash']
    ends = smooth01((X - (xa - 12)) / 16.0) * smooth01(((xb + 12) - X) / 16.0)
    drop = amount * np.maximum(y_bot - y_u, 0) * ends    # how far the lid edge travels in this column
    skin = 24.0                                          # lid skin above the lash line that stretches
    a = y_top - skin
    src = Y.copy()
    band = (Y > a) & (Y <= y_top + drop)                 # stretched skin
    src[band] = (a + (Y - a) * skin / (skin + drop))[band]
    lash = (Y > y_top + drop) & (Y <= y_u + drop)        # lash line moves down unchanged
    src[lash] = (Y - drop)[lash]
    mapy[y0:y1, x0:x1] = src
    # the lowered lash line meets untouched skin along a hard seam: mark it so it can be softened
    seam = np.zeros((h, w), np.float32)
    seam[y0:y1, x0:x1] = np.exp(-((Y - (y_u + drop)) / 1.3) ** 2) * np.clip(drop / 1.5, 0, 1)
    return xx, mapy, seam


# ---------------------------------------------------------------- shocked: wide open eyes

def shock_eye_parts(rgb, eye):
    """Split a wide-open eye into the eyeball opening, a blank eyeball and the iris as its own disc."""
    cx, cy, r = eye['iris']
    h, w, _ = rgb.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x0, x1, y0, y1 = int(cx - 60), int(cx + 60), int(cy - 34), int(cy + 34)
    win = np.zeros((h, w), bool); win[y0:y1, x0:x1] = True
    chroma = cv2.GaussianBlur(rgb[..., 0] - rgb[..., 2], (0, 0), 0.6)
    # the eyeball is neutral or bluish, the lids are warm
    core = ((chroma < 0.11) & win).astype(np.uint8)
    core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab = cv2.connectedComponents(core, connectivity=8)
    keep = lab == lab[int(round(cy)), int(round(cx))]
    region = cv2.dilate(keep.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    opening = np.clip((0.15 - chroma) / 0.05, 0, 1)
    opening = np.where(keep, np.maximum(opening, 0.999), opening) * region
    # the colour test is ragged and slightly generous (lash line above, pale lid rim below), so the
    # opening used for clipping the iris is the band between two smooth lid curves fitted to it
    lum = cv2.GaussianBlur(rgb @ LUMW, (0, 0), 0.6)
    cols = np.arange(x0, x1)
    px, top_y, top_w, low_y = [], [], [], []
    for x in cols:
        on = np.nonzero(opening[:, x] >= 0.5)[0]
        if len(on) < 3:
            continue
        t0, b0 = on.min(), on.max()
        px.append(x); low_y.append(float(b0))
        seg = lum[t0 - 3:t0 + 10, x]
        dark, bright = seg[:6].min(), seg[3:].max()
        if abs(x - cx) > r + 2 and bright > 0.6 and bright - dark > 0.2:
            k = int(np.argmax(seg >= (dark + bright) / 2))          # lash line gives way to the white
            top_y.append(t0 - 3 + k - 0.5); top_w.append(1.0)
        else:
            top_y.append(t0 + 2.7); top_w.append(0.3)                # over the iris: just inside the colour edge
    px = np.array(px, float); top_y = np.array(top_y); top_w = np.array(top_w); low_y = np.array(low_y)
    xn = (px - cx) / 50.0
    fit_top = np.polyfit(xn, top_y, 4, w=top_w)
    fit_low = np.polyfit(xn, low_y, 4)
    for _ in range(4):                                   # follow the upper envelope: dips below it are lid rim
        res = low_y - np.polyval(fit_low, xn)
        fit_low = np.polyfit(xn, low_y, 4, w=np.where(res > 0.8, 0.05, 1.0))
    xq = (xx - cx) / 50.0
    lid_top, lid_low = np.polyval(fit_top, xq), np.polyval(fit_low, xq)
    inside = cv2.dilate(opening, np.ones((5, 5), np.uint8)) > 0.5
    span = (xx >= px.min()) & (xx <= px.max())
    opening = smooth01((yy - (lid_top - 0.8)) / 1.6) * smooth01(((lid_low + 1.2) - yy) / 2.4) * inside * span

    rho = np.hypot(xx - cx, yy - cy)
    # blank eyeball: every row of the iris footprint is bridged from the clean white on either side
    rr = r + 4.0
    fill = rgb.copy()
    for y in range(int(cy - rr) - 1, int(cy + rr) + 2):
        half = np.sqrt(max(rr * rr - (y - cy) ** 2, 0.0))
        xl, xr = cx - half - 1.5, cx + half + 1.5
        cl = np.mean([sample(rgb, np.array([[xl - k]]), np.array([[float(y)]]))[0, 0] for k in (0, 1.5, 3)], axis=0)
        cr = np.mean([sample(rgb, np.array([[xr + k]]), np.array([[float(y)]]))[0, 0] for k in (0, 1.5, 3)], axis=0)
        xi = np.arange(int(xl), int(xr) + 2)
        u = smooth01((xi - xl) / max(xr - xl, 1e-3))[:, None]
        fill[y, xi] = cl * (1 - u) + cr * u
    fill = cv2.GaussianBlur(fill, (0, 0), 1.4)
    foot = smooth01((rr - rho) / 4.0)[..., None]
    blank = rgb * (1 - foot) + fill * foot

    # iris disc: real pixels where the lids did not cover it; where they did, the nearest real iris colour
    valid = (cv2.erode(opening, np.ones((5, 5), np.uint8)) > 0.9) & (rho < r - 0.8)
    _, idx = cv2.distanceTransformWithLabels((~valid).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    vy, vx = np.nonzero(valid)
    ly = np.zeros(idx.max() + 1, np.int32); lx = np.zeros(idx.max() + 1, np.int32)
    ly[idx[vy, vx]] = vy; lx[idx[vy, vx]] = vx
    near = rgb[ly[idx], lx[idx]]
    near = cv2.GaussianBlur(near, (0, 0), 1.0)
    v3 = cv2.GaussianBlur(valid.astype(np.float32), (0, 0), 0.7)[..., None]
    disc_rgb = rgb * v3 + near * (1 - v3)
    disc_a = smooth01((r + 0.9 - rho) / 1.8)
    return dict(opening=opening, blank=blank, disc_rgb=disc_rgb, disc_a=disc_a, box=(x0, x1, y0, y1), iris=eye['iris'])


def shock_frame(rgb, parts, dx, dy):
    out = rgb.copy()
    h, w, _ = rgb.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for p in parts:
        x0, x1, y0, y1 = p['box']
        sl = (slice(y0, y1), slice(x0, x1))
        X, Y = xx[sl] - dx, yy[sl] - dy
        d_rgb = sample(p['disc_rgb'], X, Y)
        d_a = np.clip(sample(p['disc_a'], X, Y), 0, 1) * p['opening'][sl]
        out[sl] = p['blank'][sl] * (1 - d_a[..., None]) + d_rgb * d_a[..., None]
    return out


# ---------------------------------------------------------------- build

def unsharp(rgb, sigma=1.1, amount=0.45):
    soft = cv2.GaussianBlur(rgb, (0, 0), sigma)
    return np.clip(rgb + amount * (rgb - soft), 0, 1)


def build():
    cv = canvases()
    frames = {}

    joy_rgb, joy_a = cv['joy'][..., :3], cv['joy'][..., 3]
    curves = [joy_eye_curves(joy_rgb, e) for e in GEO['joy']['eyes'].values()]
    shape = joy_a.shape
    frames['joy'] = joy_rgb
    for k in range(1, 5):
        for sign, tag in ((-1, 'l'), (1, 'r')):
            img = joy_rgb
            for c in curves:
                mx, my = joy_gaze_maps(c, sign * k * JOY_STEP, shape)
                img = sample(img, mx, my)
            frames[f'joy_{tag}{k}'] = img
    for name, amount in (('joy_half', 0.6), ('joy_closed', 1.0)):
        img = joy_rgb
        for c in curves:
            mx, my, seam = joy_blink_maps(c, amount, shape)
            img = sample(img, mx, my)
            soft = cv2.GaussianBlur(img, (0, 0), 0.8)
            img = img * (1 - seam[..., None]) + soft * seam[..., None]
        frames[name] = img

    sh_rgb, sh_a = cv['shocked'][..., :3], cv['shocked'][..., 3]
    parts = [shock_eye_parts(sh_rgb, e) for e in GEO['shocked']['eyes'].values()]
    for ix in range(5):
        for iy in range(3):
            frames[f's_{ix}{iy}'] = shock_frame(sh_rgb, parts, (ix - 2) * SHOCK_DX, (iy - 1) * SHOCK_DY)

    alphas = {n: (joy_a if n.startswith('joy') else sh_a) for n in frames}
    return frames, alphas, dict(curves=curves, parts=parts)


EYE_BOX = (336, 392, 688, 504)        # canvas px holding both eyes of both expressions; sides are multiples of 16
ATLAS_COLS = 3


def export(frames, alphas, out_root):
    """Write two whole faces and one small sheet of eye patches.

    Compressing 26 whole pictures separately makes the skin shimmer when they swap, because each file
    gets its own compression noise. So only the two resting faces are stored whole; every other state
    is a patch holding just the pixels that differ from its resting face, with a soft mask in its alpha.
    The page lays the patch over the resting face, so everything outside the eyes is identical in all states.
    """
    face_dir = os.path.join(out_root, 'assets', 'face')
    os.makedirs(face_dir, exist_ok=True)
    sharp = {n: unsharp(f) for n, f in frames.items()}
    bases = {'joy': 'joy', 'shock': 's_21'}
    for out_name, src in bases.items():
        px = (np.clip(np.dstack([sharp[src], alphas[src]]), 0, 1) * 255 + 0.5).astype(np.uint8)
        cv2.imwrite(os.path.join(face_dir, out_name + '.webp'), cv2.cvtColor(px, cv2.COLOR_RGBA2BGRA), [cv2.IMWRITE_WEBP_QUALITY, 90])

    x0, y0, x1, y1 = EYE_BOX
    cw, ch = x1 - x0, y1 - y0
    names = [n for n in frames if n not in bases.values()]
    rows = -(-len(names) // ATLAS_COLS)
    atlas = np.zeros((rows * ch, ATLAS_COLS * cw, 4), np.float32)
    cells = {}
    ring = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    for i, n in enumerate(names):
        rest = sharp['joy' if n.startswith('joy') else 's_21']
        diff = np.abs(sharp[n] - rest).max(axis=2)
        changed = diff > 1.5 / 255
        outside = changed.copy(); outside[y0 + 8:y1 - 8, x0 + 8:x1 - 8] = False
        assert not outside.any(), f'{n}: pixels change outside the eye box'
        m = cv2.dilate(changed[y0:y1, x0:x1].astype(np.uint8), ring).astype(np.float32)
        m = np.clip(cv2.GaussianBlur(m, (0, 0), 1.5) * 1.25, 0, 1)
        col, row = i % ATLAS_COLS, i // ATLAS_COLS
        atlas[row * ch:(row + 1) * ch, col * cw:(col + 1) * cw] = np.dstack([sharp[n][y0:y1, x0:x1], m])
        cells[n] = [col, row]
    px = (np.clip(atlas, 0, 1) * 255 + 0.5).astype(np.uint8)
    cv2.imwrite(os.path.join(face_dir, 'eyes.webp'), cv2.cvtColor(px, cv2.COLOR_RGBA2BGRA), [cv2.IMWRITE_WEBP_QUALITY, 92])

    data = dict(size=CW, box=[x0 / CW, y0 / CW, x1 / CW, y1 / CW], atlas=[atlas.shape[1], atlas.shape[0]],
                cell=[cw, ch], cells=cells, eyeV=GEO['eye_v'])
    # site icons: the head alone, cropped square
    head = np.dstack([sharp['joy'], alphas['joy']])[52:716, 180:844]
    for size, flat in ((64, False), (180, True)):
        pm = np.dstack([head[..., :3] * head[..., 3:], head[..., 3]])
        pm = cv2.resize(pm, (size, size), interpolation=cv2.INTER_AREA)
        if flat:                                          # phones want an opaque square
            bg = np.array([12, 12, 12], np.float32) / 255
            rgb = pm[..., :3] + bg * (1 - pm[..., 3:])
            out = np.dstack([rgb, np.ones((size, size), np.float32)])
        else:
            a = pm[..., 3:]
            out = np.dstack([np.where(a > 1e-3, pm[..., :3] / np.maximum(a, 1e-3), 0), a[..., 0]])
        icon = (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)
        cv2.imwrite(os.path.join(out_root, 'assets', f'icon-{size}.png'), cv2.cvtColor(icon, cv2.COLOR_RGBA2BGRA))

    js_dir = os.path.join(out_root, 'assets', 'js'); os.makedirs(js_dir, exist_ok=True)
    with open(os.path.join(js_dir, 'face-data.js'), 'w') as f:
        f.write('// Written by tools/build_faces.py: where each eye patch sits in assets/face/eyes.webp.\n')
        f.write('window.FACE_DATA = ' + json.dumps(data, separators=(',', ':')) + ';\n')


def debug_views(frames, alphas, extra, d):
    os.makedirs(d, exist_ok=True)
    z = 4

    def strip(names, box, cols):
        x0, y0, x1, y1 = box
        tiles = [cv2.resize(frames[n][y0:y1, x0:x1], None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC) for n in names]
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.concatenate(tiles[i:i + cols], axis=1) for i in range(0, len(tiles), cols)]
        return np.concatenate(rows, axis=0)

    joy_names = ['joy_l4', 'joy_l3', 'joy_l2', 'joy_l1', 'joy', 'joy_r1', 'joy_r2', 'joy_r3', 'joy_r4', 'joy_half', 'joy_closed']
    save_rgb(os.path.join(d, 'joy_eyeR.png'), strip(joy_names, (352, 440, 462, 496), 3))
    save_rgb(os.path.join(d, 'joy_eyeL.png'), strip(joy_names, (560, 436, 672, 492), 3))
    sh_names = [f's_{ix}{iy}' for iy in range(3) for ix in range(5)]
    z = 3
    save_rgb(os.path.join(d, 'shock_eyes.png'), strip(sh_names, (340, 400, 672, 472), 3))
    for n in ('joy', 'joy_l4', 'joy_r4', 'joy_closed', 's_21', 's_00', 's_42'):
        save_rgb(os.path.join(d, f'full_{n}.png'), on_dark(np.dstack([frames[n], alphas[n]])))
    for c in extra['curves']:
        print('joy eye', c['iris'], 'lash thickness %.1f' % c['lash'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--debug', help='also write enlarged check images to this folder')
    ap.add_argument('--no-export', action='store_true')
    args = ap.parse_args()
    frames, alphas, extra = build()
    if args.debug:
        debug_views(frames, alphas, extra, args.debug)
    if not args.no_export:
        export(frames, alphas, os.path.join(HERE, '..'))
    print('frames:', len(frames))
