"""Image helpers for building the portrait frames: background matting, alignment, eye synthesis."""
import numpy as np
import cv2


def load_rgb(path):
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0


def save_rgba(path, rgba):
    a = np.clip(rgba, 0, 1)
    out = (a * 255.0 + 0.5).astype(np.uint8)
    cv2.imwrite(path, cv2.cvtColor(out, cv2.COLOR_RGBA2BGRA))


def save_rgb(path, rgb):
    out = (np.clip(rgb, 0, 1) * 255.0 + 0.5).astype(np.uint8)
    cv2.imwrite(path, cv2.cvtColor(out, cv2.COLOR_RGB2BGR))


def _poly_terms(h, w):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    x = x / w - 0.5
    y = y / h - 0.5
    return np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], axis=-1)


def fit_background(img, iters=4, thr=0.045):
    """Model the studio backdrop as a smooth quadratic colour field fitted to backdrop pixels."""
    h, w, _ = img.shape
    T = _poly_terms(h, w)
    sel = np.zeros((h, w), bool)
    sel[: int(h * 0.05), :] = True
    sel[: int(h * 0.55), : int(w * 0.06)] = True
    sel[: int(h * 0.55), -int(w * 0.06):] = True
    B = None
    for _ in range(iters):
        A = T[sel]
        B = np.zeros_like(img)
        for c in range(3):
            coef, *_ = np.linalg.lstsq(A, img[..., c][sel], rcond=None)
            B[..., c] = T @ coef
        d = np.linalg.norm(img - B, axis=2)
        cand = (d < thr).astype(np.uint8)
        n, lab = cv2.connectedComponents(cand, connectivity=4)
        border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
        border = border[border != 0] if cand[0, 0] == 0 else border
        sel = np.isin(lab, border) & (cand > 0)
    return B, sel


def matte(img, band=4, thr=0.045, hair_y_max=None, fringe_reach=16):
    """Return (alpha, foreground colour, backdrop) for a subject on a plain pale backdrop.

    Backdrop pixels are those close to the fitted backdrop colour and connected to the image border.
    Above hair_y_max the backdrop is grown into pale neutral rim strands of the hair, which would
    otherwise read as a white fringe on a dark page. In a thin band along the edge, alpha comes from
    projecting the pixel between the backdrop colour and the nearest solid subject colour, and the
    colour is un-mixed so no backdrop tint is left.
    """
    lum_w = np.array([0.299, 0.587, 0.114], np.float32)
    el = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    B, bg = fit_background(img, thr=thr)
    h, w, _ = img.shape
    if hair_y_max is not None:
        lum = img @ lum_w
        rows = (np.arange(h) < hair_y_max)[:, None]
        neutral = (img[..., 0] - img[..., 2]) < 0.05
        light = neutral & (lum > 0.36) & rows & ~bg
        n, lab = cv2.connectedComponents(light.astype(np.uint8), connectivity=8)
        seed = (cv2.dilate(bg.astype(np.uint8), el(2)) > 0) & light
        touch = np.unique(lab[seed])
        fringe = np.isin(lab, touch[touch != 0]) & (cv2.dilate(bg.astype(np.uint8), el(fringe_reach)) > 0)
        bg = bg | fringe
        bg = cv2.morphologyEx(bg.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
    near_bg = cv2.dilate(bg.astype(np.uint8), el(band)) > 0
    core = ~near_bg
    _, idx = cv2.distanceTransformWithLabels((~core).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(core)
    lut_y = np.zeros(idx.max() + 1, np.int32)
    lut_x = np.zeros(idx.max() + 1, np.int32)
    lut_y[idx[ys, xs]] = ys
    lut_x[idx[ys, xs]] = xs
    F = img[lut_y[idx], lut_x[idx]]
    fb = F - B
    alpha = np.sum((img - B) * fb, axis=2) / np.maximum(np.sum(fb * fb, axis=2), 1e-4)
    alpha = np.clip(alpha, 0, 1)
    alpha[core] = 1.0
    alpha[bg] = 0.0
    a3 = alpha[..., None]
    unmixed = np.clip((img - (1 - a3) * B) / np.maximum(a3, 0.05), 0, 1)
    wgt = np.clip((a3 - 0.2) / 0.4, 0, 1)
    fg = unmixed * wgt + F * (1 - wgt)
    fg[core] = img[core]
    if hair_y_max is not None:
        # pale glints left along the hair outline are recoloured with the dark hair beside them
        edge = (cv2.dilate(bg.astype(np.uint8), el(10)) > 0) & rows & (alpha > 0)
        fl = fg @ lum_w
        pale = edge & ((fg[..., 0] - fg[..., 2]) < 0.05) & (fl > 0.30)
        dark = cv2.erode(fg, np.ones((11, 11), np.uint8))
        w = np.clip((fl - 0.30) / 0.15, 0, 1)[..., None] * pale[..., None]
        fg = fg * (1 - w) + dark * w
    return alpha.astype(np.float32), fg.astype(np.float32), B


def similarity(src, dst):
    """Least-squares similarity transform (scale, rotation, translation) taking src points to dst, as 2x3."""
    src = np.asarray(src, np.float64); dst = np.asarray(dst, np.float64)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = d.T @ s / len(src)
    U, D, Vt = np.linalg.svd(cov)
    sign = np.sign(np.linalg.det(U @ Vt))
    Dm = np.diag([1.0, sign])
    R = U @ Dm @ Vt
    scale = np.trace(np.diag(D) @ Dm) / s.var(0).sum()
    t = mu_d - scale * R @ mu_s
    return np.hstack([scale * R, t[:, None]])


def compose_affine(A, B):
    """Apply B first, then A (both 2x3)."""
    A3 = np.vstack([A, [0, 0, 1]]); B3 = np.vstack([B, [0, 0, 1]])
    return (A3 @ B3)[:2]


def apply_affine(M, pts):
    pts = np.asarray(pts, np.float64)
    return pts @ M[:, :2].T + M[:, 2]


def warp_rgba(fg, alpha, M, size):
    """Resample a cut-out into canvas space in premultiplied form; returns straight RGBA float."""
    pm = np.dstack([fg * alpha[..., None], alpha]).astype(np.float32)
    out = cv2.warpAffine(pm, M.astype(np.float64), (size, size), flags=cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = np.clip(out[..., 3], 0, 1)
    rgb = np.where(a[..., None] > 1e-3, out[..., :3] / np.maximum(a[..., None], 1e-3), 0)
    return np.dstack([np.clip(rgb, 0, 1), a]).astype(np.float32)


def bust_mask(size, cx, cy, rx, ry, inner=0.78):
    """1 over the head, fading to 0 along an ellipse below cy so the shoulders melt away."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    d = np.sqrt(((x - cx) / rx) ** 2 + (np.maximum(y - cy, 0) / ry) ** 2)
    t = np.clip((d - inner) / (1 - inner), 0, 1)
    return 1 - t * t * (3 - 2 * t)


def on_dark(rgba, col=(12, 12, 12)):
    c = np.array(col, np.float32) / 255
    return rgba[..., :3] * rgba[..., 3:4] + c * (1 - rgba[..., 3:4])
