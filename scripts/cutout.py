#!/usr/bin/env python3
"""Cut generated pictures on a flat chroma background (#00FF00) into sprites with soft alpha. Local, no network.

  cutout.py cut  work/gen/heroes.jpg assets/img/heroes            → heroes_0.webp, heroes_1.webp … + heroes.json
  cutout.py cut  work/gen/lamp.jpg   assets/img/lamp --whole      → lamp.webp (whole picture, no splitting)
  cutout.py glyphs work/gen/letters_yellow.jpg assets/img/gl --rows "АБВГДЕЗ,ИЙЛМНОП,РСТШЫЯ-" --name y
                                                                   → y_0410.webp … + glyphs.json (merged)
Keys (--key):
  green (default)  green dominance with a feathered edge, 1 px choke, green spill pulled down; if the generator
                   already returned a transparent PNG, its alpha is kept (choke + edge despill only)
  dist             distance to the background colour sampled at the borders: keeps green objects
                   (flasks, globes, backpacks) that the green key would eat; despill only on the rim
  white            dark ink on white paper (sketches): alpha from darkness, ink recoloured to --ink
Splitting: parts of one object stay together (mask dilated by --dil px before grouping); pieces smaller than
--min px² are dropped; order is by rows (--row px tall), then left to right. Glyph files keep an 8 px margin
on every side (ink height = h - 16); to assemble a word, scale each glyph by the median ink height of its row and
subtract the 8 px margins in the spacing (one span per letter, shared baseline). Thin details (paper clips, strings)
often break: check every sprite by eye.
"""
import argparse
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def soft(a, choke=3, blur=.7):
    img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(choke))
    return np.asarray(img.filter(ImageFilter.GaussianBlur(blur))).astype(np.float32) / 255


def key_green(src):
    if src.mode == 'RGBA' and (np.asarray(src)[..., 3] < 10).mean() > .2:
        im = np.asarray(src).astype(np.float32)
        r, g, b = im[..., 0], im[..., 1], im[..., 2]
        return np.dstack([r, np.minimum(g, np.maximum(r, b) + 12), b, soft(im[..., 3] / 255, blur=.6) * 255])
    im = np.asarray(src.convert('RGB')).astype(np.float32)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    green = g - np.maximum(r, b)
    a = 1 - np.clip((green - 28) / (95 - 28), 0, 1)
    a[(g > 150) & (green > 70)] = 0
    a = soft(a)
    g2 = g - np.clip(green, 0, None) * np.clip(1.15 - a * .2, 0, 1)
    return np.dstack([r, g2, b, a * 255])


def key_dist(src):
    im = np.asarray(src.convert('RGB')).astype(np.float32)
    border = np.concatenate([im[:8].reshape(-1, 3), im[-8:].reshape(-1, 3), im[:, :8].reshape(-1, 3), im[:, -8:].reshape(-1, 3)])
    d = np.sqrt(((im - np.median(border, axis=0)) ** 2).sum(axis=2))
    a = soft((d - 55) / (125 - 55), blur=.8)
    rim = np.asarray(Image.fromarray((a > .99).astype(np.uint8) * 255).filter(ImageFilter.MinFilter(7))) == 0
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    return np.dstack([r, np.where(rim, np.minimum(g, np.maximum(r, b) + 6), g), b, a * 255])


def key_white(src, ink):
    im = np.asarray(src.convert('RGB')).astype(np.float32)
    a = np.clip((236 - im.mean(axis=2)) / 150, 0, 1) ** .8
    return np.dstack([np.zeros_like(im) + ink, a * 255])


def keyed(path, how, ink=(52, 50, 58)):
    src = Image.open(path)
    rgba = key_dist(src) if how == 'dist' else key_white(src, ink) if how == 'white' else key_green(src)
    return rgba.clip(0, 255).astype(np.uint8)


def label(mask):
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    n = 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if lab[y0, x0]:
            continue
        n += 1
        lab[y0, x0] = n
        q = deque([(y0, x0)])
        while q:
            y, x = q.popleft()
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n
                    q.append((yy, xx))
    return lab, n


def pieces(rgba, dil=9, min_area=3000, row=500, threshold=40):
    """[(x0, y0, x1, y1, mask)] of object clusters, ordered by rows then x."""
    mask = rgba[..., 3] > threshold
    q = 4
    small = Image.fromarray((mask * 255).astype(np.uint8)).resize((mask.shape[1] // q, mask.shape[0] // q))
    lab, n = label(np.asarray(small.filter(ImageFilter.MaxFilter(dil // 2 * 2 + 1))) > 0)
    items = []
    for k in range(1, n + 1):
        cl = lab == k
        if cl.sum() * q * q < min_area:
            continue
        full = np.kron(cl, np.ones((q, q), bool))
        full = np.pad(full, ((0, mask.shape[0] - full.shape[0]), (0, mask.shape[1] - full.shape[1])))
        ys, xs = np.nonzero(full & mask)
        if len(ys):
            items.append((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1, full))
    items.sort(key=lambda it: (round((it[1] + it[3]) / 2 / row), it[0]))
    return items


def save(rgba, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(rgba)
    img.save(path, quality=92, method=5) if path.suffix == '.webp' else img.save(path, optimize=True)


def crop(rgba, box, pad=6):
    x0, y0, x1, y1, full = box
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(rgba.shape[1], x1 + pad), min(rgba.shape[0], y1 + pad)
    piece = rgba[y0:y1, x0:x1].copy()
    piece[..., 3] = np.where(full[y0:y1, x0:x1], piece[..., 3], 0)
    return piece, (int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def cmd_cut(a):
    rgba = keyed(a.src, a.key)
    dst, ext = Path(a.dst), '.' + a.format
    if a.whole:
        save(rgba, dst.with_name(dst.name + ext))
        return [{'file': dst.name + ext, 'w': rgba.shape[1], 'h': rgba.shape[0]}]
    meta = []
    for i, box in enumerate(pieces(rgba, a.dil, a.min, a.row)):
        piece, (x, y, w, h) = crop(rgba, box)
        name = f'{dst.name}_{i}{ext}'
        save(piece, dst.with_name(name))
        meta.append({'file': name, 'w': w, 'h': h, 'x': x, 'y': y})
    dst.with_name(dst.name + '.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def cmd_glyphs(a):
    rows = a.rows.split(',')
    rgba = keyed(a.src, a.key)
    items = pieces(rgba, a.dil, a.min, 1, threshold=60)      # Й's breve and Ы's two parts stay one glyph
    items.sort(key=lambda it: (it[1] + it[3]) / 2)
    lines, cur = [], [items[0]]
    for it in items[1:]:
        if (it[1] + it[3]) / 2 - (cur[-1][1] + cur[-1][3]) / 2 > a.row / 2:
            lines.append(cur)
            cur = [it]
        else:
            cur.append(it)
    lines.append(cur)
    if [len(x) for x in lines] != [len(r) for r in rows]:
        raise SystemExit(f'found {[len(x) for x in lines]} glyphs per row, --rows expects {[len(r) for r in rows]}; '
                         'regenerate the sheet with wider gaps or fix --rows')
    out = Path(a.dst)
    meta_path = out / 'glyphs.json'
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    for chars, line in zip(rows, lines):
        line.sort(key=lambda it: it[0])
        for ch, box in zip(chars, line):
            piece, (_, _, w, h) = crop(rgba, box, pad=8)
            name = f'{a.name}_{ord(ch):04x}.{a.format}'
            save(piece, out / name)
            meta[a.name + ch] = {'file': name, 'w': w, 'h': h, 'pad': 8}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return {'glyphs': sum(len(r) for r in rows), 'json': str(meta_path)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('cut', 'glyphs'):
        s = sub.add_parser(name)
        s.add_argument('src')
        s.add_argument('dst', help='cut: output prefix (dir/name); glyphs: output directory')
        s.add_argument('--key', choices=('green', 'dist', 'white'), default='green')
        s.add_argument('--format', choices=('webp', 'png'), default='webp')
        s.add_argument('--dil', type=int, default=9, help='join gaps up to ~4×dil px (dilation on a 1/4 grid)')
        s.add_argument('--min', type=int, default=3000 if name == 'cut' else 6400, help='px²: smaller pieces are dropped')
        s.add_argument('--row', type=int, default=500, help='px: row height for ordering')
        if name == 'cut':
            s.add_argument('--whole', action='store_true')
        else:
            s.add_argument('--rows', required=True, help='characters per sheet row, comma separated')
            s.add_argument('--name', default='g', help='prefix of files and json keys (e.g. colour)')
    a = p.parse_args()
    print(json.dumps(cmd_cut(a) if a.cmd == 'cut' else cmd_glyphs(a), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
