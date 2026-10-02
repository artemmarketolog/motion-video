#!/usr/bin/env python3
"""Build a standalone composition that renders frames [f0, f1) of a HyperFrames index.html.

The source frame n of the segment equals frame f0+n of the full render, because
the registered GSAP timeline is wrapped in tweenFromTo(t0, t1) and every timed
element is shifted by -t0. Audio elements are removed: sound is mixed separately.
Assets are hard-linked (never symlinked: the render sandbox cannot follow links
outside the mounted folder).
"""
import argparse
import html
import json
import os
import re
import shutil
from pathlib import Path

TAG = re.compile(r'<(?P<name>[a-zA-Z][\w-]*)(?P<attrs>(?:[^>"\']|"[^"]*"|\'[^\']*\')*)>', re.S)
ATTR = re.compile(r'([\w:-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')
REF = re.compile(r'''(?:src|href|data-composition-src|poster)\s*=\s*["']([^"'#]+)["']|url\(\s*["']?([^"')#]+)["']?\s*\)''')


def attrs_of(text):
    return {m.group(1): html.unescape(m.group(3) if m.group(3) is not None else m.group(4)) for m in ATTR.finditer(text)}


def set_attr(tag_text, name, value):
    pattern = re.compile(r'(\s' + re.escape(name) + r'\s*=\s*)("[^"]*"|\'[^\']*\')')
    if pattern.search(tag_text):
        return pattern.sub(lambda m: m.group(1) + '"' + value + '"', tag_text, count=1)
    return tag_text[:-1].rstrip('/') + f' {name}="{value}"' + ('/>' if tag_text.endswith('/>') else '>')


def fmt(x):
    return f'{x:.6f}'.rstrip('0').rstrip('.') or '0'


def local_refs(source):
    refs = set()
    for m in REF.finditer(source):
        ref = (m.group(1) or m.group(2) or '').strip()
        if not ref or re.match(r'^(?:[a-z]+:|//|data:)', ref, re.I):
            continue
        refs.add(ref.split('?')[0])
    return refs


def composition_info(source):
    root = None
    for m in TAG.finditer(source):
        a = attrs_of(m.group('attrs'))
        if 'data-composition-id' in a:
            root = (m, a)
            break
    if root is None:
        raise ValueError('No element with data-composition-id')
    a = root[1]
    return {'id': a['data-composition-id'], 'fps': float(a.get('data-fps', 30)),
            'duration': float(a['data-duration']), 'width': int(a['data-width']), 'height': int(a['data-height'])}


def make_segment_html(source, ranges, fps):
    """ranges: list of (f0, f1) frame ranges rendered back to back in one composition."""
    info = composition_info(source)
    total = sum(f1 - f0 for f0, f1 in ranges)
    timed = []
    out, pos, root_done = [], 0, False
    for m in TAG.finditer(source):
        name, raw = m.group('name').lower(), m.group(0)
        a = attrs_of(m.group('attrs'))
        new = raw
        if not root_done and 'data-composition-id' in a:
            new = set_attr(raw, 'data-duration', fmt(total / fps))
            root_done = True
        elif name == 'audio':
            end = source.find('</audio>', m.end())
            out.append(source[pos:m.start()])
            pos = end + len('</audio>') if end >= 0 else m.end()
            continue
        elif 'data-start' in a:
            timed.append(a.get('id') or name)
            if len(ranges) != 1:
                raise ValueError('Multi-range segments support only compositions without timed clips')
            t0, t1 = ranges[0][0] / fps, ranges[0][1] / fps
            start = float(a['data-start'])
            duration = float(a['data-duration']) if 'data-duration' in a else None
            end = start + duration if duration is not None else None
            if end is not None and (end <= t0 or start >= t1):
                if name == 'video':   # a clip outside the range is dropped: HyperFrames rejects unrendered clips
                    close = source.find('</video>', m.end())
                    out.append(source[pos:m.start()])
                    pos = close + len('</video>') if close >= 0 else m.end()
                    continue
                new = set_attr(set_attr(raw, 'data-start', fmt(t1 - t0 + 1)), 'data-duration', '0.001')
            else:
                shift = max(0.0, t0 - start)
                new = set_attr(raw, 'data-start', fmt(max(0.0, start - t0)))
                if duration is not None:
                    new = set_attr(new, 'data-duration', fmt(min(end, t1) - max(start, t0)))
                if shift and name == 'video':
                    rate = float(a.get('data-playback-rate', 1))
                    new = set_attr(new, 'data-media-start', fmt(float(a.get('data-media-start', 0)) + shift * rate))
        out.append(source[pos:m.start()])
        out.append(new)
        pos = m.end()
    out.append(source[pos:])
    body = ''.join(out)
    pieces = ','.join(f'[{fmt(f0 / fps)},{fmt(f1 / fps)}]' for f0, f1 in ranges)
    # Explicit duration: GSAP otherwise sizes tweenFromTo lazily on play, and a
    # seek-only renderer sees a zero-length segment timeline.
    wrapper = ('<script>\n(function () {\n'
               '  var source = window.__timelines && window.__timelines[' + json.dumps(info['id']) + '];\n'
               '  if (!source) throw new Error("segment: timeline not registered");\n'
               '  var seg = gsap.timeline({ paused: true });\n'
               '  [' + pieces + '].forEach(function (r) {\n'
               '    seg.add(source.tweenFromTo(r[0], r[1], { duration: r[1] - r[0], ease: "none", immediateRender: false }));\n'
               '  });\n'
               '  window.__timelines = window.__timelines || {};\n'
               '  window.__timelines[' + json.dumps(info['id']) + '] = seg;\n'
               '})();\n</script>')
    idx = body.rfind('</body>')
    if idx < 0:
        raise ValueError('index.html has no </body>')
    return body[:idx] + wrapper + '\n' + body[idx:], timed


def link_tree(project, dest, source):
    dest.mkdir(parents=True)
    for ref in sorted(local_refs(source)):
        src = (project / ref).resolve()
        if not src.is_relative_to(project):
            raise ValueError(f'Reference escapes project: {ref}')
        if not src.is_file():
            raise ValueError(f'Missing referenced file: {ref}')
        target = dest / src.relative_to(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, target)
        except OSError:
            shutil.copy2(src, target)
        if target.suffix == '.html':
            for sub in local_refs(src.read_text()):
                subsrc = (src.parent / sub).resolve()
                if subsrc.is_file() and subsrc.is_relative_to(project):
                    t2 = dest / subsrc.relative_to(project)
                    if not t2.exists():
                        t2.parent.mkdir(parents=True, exist_ok=True)
                        os.link(subsrc, t2)


def build(project, dest, ranges):
    project = Path(project).resolve()
    source = (project / 'index.html').read_text()
    info = composition_info(source)
    fps = info['fps']
    text, timed = make_segment_html(source, ranges, fps)
    link_tree(project, dest, source)
    (dest / 'index.html').write_text(text)
    return {'dir': str(dest), 'frames': sum(b - a for a, b in ranges), 'timed_elements': timed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('dest', type=Path)
    parser.add_argument('--frames', required=True, help='f0:f1[,f0:f1] frame ranges, end exclusive')
    args = parser.parse_args()
    ranges = [tuple(int(x) for x in part.split(':')) for part in args.frames.split(',')]
    if args.dest.exists():
        parser.error('Destination exists')
    print(json.dumps(build(args.project, args.dest.resolve(), ranges), ensure_ascii=False))


if __name__ == '__main__':
    main()
