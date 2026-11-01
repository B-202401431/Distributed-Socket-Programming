#!/usr/bin/env python3
"""Copy a reproducible image subset without changing the original dataset."""
import argparse,json,shutil
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--source',required=True,type=Path,help='Original raw-img root')
p.add_argument('--output',type=Path,default=Path('demo_dataset'))
p.add_argument('--topic',default='cane')
p.add_argument('--count',type=int,default=200)
a=p.parse_args()
if a.count<1:p.error('count must be positive')
if Path(a.topic).name != a.topic or a.topic in ('.','..'):p.error('topic must be a directory name')
source=a.source.resolve()/a.topic
if not source.is_dir():p.error('Topic directory not found: '+str(source))
files=sorted(f for f in source.iterdir() if f.is_file() and not f.is_symlink() and f.suffix.lower() in {'.jpg','.jpeg','.png','.bmp','.webp'})
if len(files)<a.count:p.error('Not enough images in source topic')
if a.output.exists():p.error('Output already exists; choose a new directory')
dest=a.output/a.topic
dest.mkdir(parents=True)
for f in files[:a.count]:shutil.copy2(f,dest/f.name)
(a.output/'SUBSET_INFO.json').write_text(json.dumps({'kind':'DEMONSTRATION SUBSET, not full Animals10','source':str(source),'count':a.count,'selection':'first image filenames in sorted order','files':[f.name for f in files[:a.count]]},indent=2))
print(f'Copied {a.count} images to {dest}. Original dataset unchanged.')
