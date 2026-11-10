#!/usr/bin/env python3
"""Measure a new pair of faces and write tools/geometry.json, which build_faces.py reads.

Inputs (tools/src): joy.png      the resting face (smiling, narrow eyes)
                    shocked.png  the reaction face (wide-open eyes)
Both are one head on a plain pale backdrop, roughly the same framing.

What it works out:
  - where the eyes are (face landmarks), which fixes the scale and position on the canvas
  - how to lay the reaction face over the resting face: scale, rotation and shift that make the
    hair and ears coincide, so the head does not jump when the pictures swap
  - the iris circle of each eye, and the left and right ends of the resting face's eye slits

Always look at the check images (--debug DIR) afterwards. A circle that misses its iris can be
corrected by hand in geometry.json: every number there is in canvas pixels.

Setup:  pip install mediapipe opencv-python-headless scipy numpy
        apt-get install -y libegl1 libgles2        (mediapipe will not load without them)
The landmark model is downloaded into tools/.cache on first use.
"""
import argparse
import json
import os
import urllib.request

import cv2
import numpy as np
from scipy.optimize import minimize

from facekit import apply_affine, compose_affine, load_rgb, matte, warp_rgba

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
CW, SCALE, EYE_V = 1024, 1.5, 0.455           # canvas size, source-to-canvas scale, height of the eye line
BUST = dict(cy=700, rx=440, ry=240)           # where the shoulders fade out
LUMW = np.array([0.299, 0.587, 0.114], np.float32)
IRIS = {'R': 468, 'L': 473}                   # R is the subject's right eye, on the left of the picture
CORNERS = {'R': (33, 133), 'L': (362, 263)}
NOSE_TIP = 4


def find_landmarks(rgb, model):
    """478 face landmarks in source pixels (the last ten are the two irises)."""
    import mediapipe as mp
    from mediapipe.tasks import python as mpp
    from mediapipe.tasks.python import vision
    det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mpp.BaseOptions(model_asset_path=model), num_faces=1))
    h, w, _ = rgb.shape
    big = cv2.resize((rgb * 255).astype(np.uint8), (w * 2, h * 2), interpolation=cv2.INTER_LANCZOS4)
    res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(big)))
    det.close()
    if not res.face_landmarks:
        raise SystemExit('no face found')
    return np.array([[p.x * w, p.y * h] for p in res.face_landmarks[0]])


def align_outline(alpha_rest, alpha_react, cut_y):
    """Similarity transform taking the reaction face onto the resting face.

    Only the outline above cut_y is compared. Hair, temples and ears are rigid; cheeks, jaw and every
    facial feature move with the expression, so fitting to landmarks instead leaves the head jumping.
    """
    h, w = alpha_rest.shape
    ref = cv2.GaussianBlur(alpha_rest, (0, 0), 1.5); ref[cut_y:] = 0
    src = cv2.GaussianBlur(alpha_react, (0, 0), 1.5)
    centre = (w / 2, h * 0.35)

    def matrix(p):
        s, r, tx, ty = p
        m = cv2.getRotationMatrix2D(centre, -r, s)
        m[0, 2] += tx; m[1, 2] += ty
        return m

    def cost(p):
        m = cv2.warpAffine(src, matrix(p), (w, h), flags=cv2.INTER_LINEAR); m[cut_y:] = 0
        return float(np.abs(m - ref).sum())

    best = None
    for s0 in (0.96, 0.98, 1.0, 1.02):
        for r0 in (-1.0, 0.0, 1.0):
            simplex = np.array([[s0, r0, 0, 0], [s0 + .02, r0, 0, 0], [s0, r0 + 1, 0, 0], [s0, r0, 6, 0], [s0, r0, 0, 6]])
            r = minimize(cost, [s0, r0, 0, 0], method='Nelder-Mead',
                         options={'xatol': 0.02, 'fatol': 1.0, 'maxiter': 400, 'initial_simplex': simplex})
            if best is None or r.fun < best.fun:
                best = r
    return matrix(best.x), best.fun


def fit_iris(lum, guess, half_angle, radius=None, reach=7.0):
    """Circle whose left and right arcs sit on the strongest dark-to-light edge (iris to white)."""
    cx0, cy0, r0 = guess
    th = np.radians(np.concatenate([np.linspace(-half_angle, half_angle, 25), np.linspace(180 - half_angle, 180 + half_angle, 25)]))
    cos, sin = np.cos(th), np.sin(th)
    radii = [radius] if radius else np.arange(r0 - 5, r0 + 3.01, 0.5)
    best = (-1.0, None)
    for cx in np.arange(cx0 - reach, cx0 + reach + 0.01, 0.5):
        for cy in np.arange(cy0 - 4, cy0 + 4.01, 0.5):
            for r in radii:
                out = cv2.remap(lum, np.float32(cx + (r + 1.5) * cos)[None], np.float32(cy + (r + 1.5) * sin)[None], cv2.INTER_LINEAR)[0]
                inn = cv2.remap(lum, np.float32(cx + (r - 1.5) * cos)[None], np.float32(cy + (r - 1.5) * sin)[None], cv2.INTER_LINEAR)[0]
                score = float(np.sort(out - inn)[5:-5].mean())
                if score > best[0]:
                    best = (score, [float(cx), float(cy), float(r)])
    return best[1], best[0]


def check_image(rgb, eyes, path):
    """Enlarged eyes with the fitted circles (and slit ends) drawn on, for a human to look at."""
    z, tiles = 8, []
    for e in eyes.values():
        cx, cy, r = e['iris']
        x0, y0 = int(cx - 62), int(cy - 36)
        big = cv2.resize(rgb[y0:y0 + 72, x0:x0 + 124], None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC)
        big = (np.clip(big, 0, 1) * 255).astype(np.uint8).copy()
        cv2.circle(big, (int((cx - x0) * z), int((cy - y0) * z)), int(r * z), (255, 0, 255), 1)
        for x in (e.get('xa'), e.get('xb')):
            if x is not None:
                cv2.line(big, (int((x - x0) * z), 0), (int((x - x0) * z), 72 * z), (0, 255, 0), 1)
        tiles.append(big)
    cv2.imwrite(path, cv2.cvtColor(np.concatenate(tiles, axis=0), cv2.COLOR_RGB2BGR))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(HERE, 'geometry.json'))
    ap.add_argument('--model', default=os.path.join(HERE, '.cache', 'face_landmarker.task'))
    ap.add_argument('--debug', help='folder for the check images')
    args = ap.parse_args()
    if not os.path.exists(args.model):
        os.makedirs(os.path.dirname(args.model), exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, args.model)

    img = {n: load_rgb(os.path.join(HERE, 'src', n + '.png')) for n in ('joy', 'shocked')}
    lm = {n: find_landmarks(img[n], args.model) for n in img}
    hair_y = {n: float((lm[n][468, 1] + lm[n][473, 1]) / 2 - 18) for n in img}     # the hair outline ends above the ears
    cut = {n: matte(img[n], hair_y_max=hair_y[n])[:2] for n in img}                 # (alpha, colour)

    to_joy, miss = align_outline(cut['joy'][0], cut['shocked'][0], int(lm['joy'][NOSE_TIP, 1] + 10))
    print('outline fit: scale %.4f, mismatch %.0f' % (np.hypot(to_joy[0, 0], to_joy[1, 0]), miss))

    mid = (lm['joy'][468] + lm['joy'][473]) / 2
    t_joy = np.array([[SCALE, 0, CW / 2 - SCALE * mid[0]], [0, SCALE, CW * EYE_V - SCALE * mid[1]]])
    place = {'joy': t_joy, 'shocked': compose_affine(t_joy, to_joy)}
    canvas = {n: warp_rgba(cut[n][1], cut[n][0], place[n], CW)[..., :3] for n in img}
    pts = {n: apply_affine(place[n], lm[n]) for n in img}

    # wide-open eyes first: the whole iris shows, so its radius can be measured. The narrow eyes show
    # only a band of it, so they borrow that radius and only their centre is fitted.
    eyes = {'joy': {}, 'shocked': {}}
    lum = {n: canvas[n] @ LUMW for n in img}
    for tag, i in IRIS.items():
        guess = [*pts['shocked'][i], np.linalg.norm(pts['shocked'][i + 1] - pts['shocked'][i + 3]) / 2]
        circle, score = fit_iris(lum['shocked'], guess, 40)
        eyes['shocked'][tag] = {'iris': [round(v, 1) for v in circle]}
        print('shocked %s iris %s (edge %.2f)' % (tag, eyes['shocked'][tag]['iris'], score))
    radius = float(np.mean([e['iris'][2] for e in eyes['shocked'].values()]))
    for tag, i in IRIS.items():
        circle, score = fit_iris(lum['joy'], [*pts['joy'][i], radius], 20, radius=radius, reach=6.0)
        xs = [pts['joy'][c][0] for c in CORNERS[tag]]
        eyes['joy'][tag] = {'iris': [round(v, 1) for v in circle], 'xa': float(np.floor(min(xs) - 4)), 'xb': float(np.ceil(max(xs) + 4))}
        print('joy %s iris %s (edge %.2f) slit %.0f..%.0f' % (tag, eyes['joy'][tag]['iris'], score, eyes['joy'][tag]['xa'], eyes['joy'][tag]['xb']))

    geo = {
        'canvas': CW, 'scale': SCALE, 'eye_v': EYE_V, 'bust': BUST,
        'joy': {'eye_mid_src': [round(float(v), 2) for v in mid], 'hair_y_max_src': round(hair_y['joy'], 1), 'eyes': eyes['joy']},
        'shocked': {'to_joy': [[round(float(v), 6) for v in row] for row in to_joy],
                    'hair_y_max_src': round(hair_y['shocked'], 1), 'eyes': eyes['shocked']},
    }
    with open(args.out, 'w') as f:
        json.dump(geo, f, indent=2)
    print('wrote', args.out)
    if args.debug:
        os.makedirs(args.debug, exist_ok=True)
        for n in img:
            check_image(canvas[n], eyes[n], os.path.join(args.debug, f'eyes_{n}.png'))
        blend = 0.5 * canvas['joy'] + 0.5 * canvas['shocked']
        cv2.imwrite(os.path.join(args.debug, 'overlay.png'), cv2.cvtColor((np.clip(blend, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))


if __name__ == '__main__':
    main()
