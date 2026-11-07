#!/usr/bin/env python3
"""Join observed Qt steps into one silent, captioned before/after comparison."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before = json.loads((args.before / 'walkthrough.json').read_text())
    after = json.loads((args.after / 'walkthrough.json').read_text())
    if [step['id'] for step in before['steps']] != [step['id'] for step in after['steps']]:
        raise ValueError('Before and after must have the same observed tasks')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    timeline = []
    chapters = [';FFMETADATA1']
    position = 0
    last = None
    for old, new in zip(before['steps'], after['steps']):
        start = position
        for directory, step in ((args.before, old), (args.after, new)):
            path = (directory / step['image']).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            last = str(path).replace("'", "'\\''")
            timeline += [f"file '{last}'", f"duration {step['seconds']}"]
            position += step['seconds'] * 1000
        chapters += ['[CHAPTER]', 'TIMEBASE=1/1000', f'START={start}',
                     f'END={position}', f"title={old['id']}"]
    timeline.append(f"file '{last}'")
    concat = args.output.with_suffix('.timeline.txt')
    metadata = args.output.with_suffix('.chapters.txt')
    concat.write_text('\n'.join(timeline) + '\n')
    metadata.write_text('\n'.join(chapters) + '\n')
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'concat', '-safe', '0', '-i', str(concat),
                    '-i', str(metadata), '-map_metadata', '1', '-map_chapters', '1',
                    '-vf', 'fps=10', '-an', '-c:v', 'libx264', '-preset', 'medium',
                    '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                    str(args.output)], check=True)
    print(args.output)


if __name__ == '__main__':
    main()
