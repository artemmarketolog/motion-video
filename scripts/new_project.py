#!/usr/bin/env python3
"""Create a new video folder from a motion-video template (no upstream init, no network).

  new_project.py /ABS/VIDEO --template footage-ad|explainer|chat-ui|kinetic-type|photo-editorial|blank [--format 9:16|4:5|3:4|1:1|16:9] [--merge]
Copies the template build.py, a BRIEF.md to fill in, empty work/ and output/.
--merge: the folder already exists (e.g. ref/ or work/ prepared by the coordinator): add only the missing
template files, never overwrite anything; prints what was added and what was kept.
Next: edit BRIEF.md and build.py, `python3 build.py`, then `mv.py build` (see SKILL.md).
"""
import argparse
import json
import shutil
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
FORMATS = ('9:16', '4:5', '3:4', '1:1', '16:9')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--template', required=True, choices=sorted(p.name for p in (SKILL / 'assets/templates').iterdir()))
    parser.add_argument('--format', choices=FORMATS)
    parser.add_argument('--merge', action='store_true', help='add missing template files to an existing folder')
    args = parser.parse_args()
    dest = args.directory.resolve()
    if dest.exists() and not args.merge:
        parser.error('Destination exists; add --merge to fill in only the missing template files, or choose a new directory')
    for bad in (Path.home() / 'workspace', Path.home() / 'projects', Path.home(), SKILL):
        if dest == bad:
            parser.error('Use a dedicated video folder')
    src = SKILL / 'assets/templates' / args.template
    build_src = (src / 'build.py').read_text() if (src / 'build.py').exists() else ''
    allowed = next((line.split('=', 1)[1] for line in build_src.splitlines() if line.startswith('FORMATS_OK =')), '')
    if args.format and build_src and f"'{args.format}'" not in allowed:
        parser.error(f'template {args.template} supports {allowed.split("#")[0].strip()}')
    files = {p.relative_to(src): p for p in src.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    files[Path('BRIEF.md')] = SKILL / 'assets/brief-template.md'
    added, kept = [], []
    for rel, path in sorted(files.items()):
        target = dest / rel
        if target.exists():
            kept.append(str(rel))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        added.append(str(rel))
    if not (dest / '.motion-skill').exists():
        (dest / '.motion-skill').write_text(str(SKILL) + '\n')
    (dest / 'work').mkdir(exist_ok=True)
    (dest / 'output').mkdir(exist_ok=True)
    if args.format:   # only files copied just now; an existing build.py or creative.json is never edited
        if 'creative.json' in added:   # data-driven template: the format lives in creative.json
            creative = dest / 'creative.json'
            data = json.loads(creative.read_text())
            data['format'] = args.format
            creative.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')
        elif 'build.py' in added:
            build = dest / 'build.py'
            lines = [f"FORMAT = '{args.format}'" if line.startswith('FORMAT = ') else line for line in build.read_text().splitlines()]
            build.write_text('\n'.join(lines) + '\n')
    print(dest)
    if args.merge:
        print(json.dumps({'added': added, 'kept_existing': kept}, ensure_ascii=False))


if __name__ == '__main__':
    main()
