"""Create distributable archives without touching originals or local settings."""
from pathlib import Path
import hashlib
import shutil
import zipfile
import argparse

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--dist', type=Path, default=root / 'dist')
dist = parser.parse_args().dist.resolve()
app = dist / 'ImageFlow'
assert (app / 'ImageFlow.exe').is_file(), 'Build the application first.'
docs = app / 'docs'
docs.mkdir(exist_ok=True)
for name in ['README.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE']:
    shutil.copyfile(root / name, app / name)
shutil.copyfile(root / 'docs' / 'TEST_REPORT.md', docs / 'TEST_REPORT.md')

portable = dist / 'ImageFlow-portable-win64.zip'
source = dist / 'ImageFlow-source.zip'
for archive in [portable, source]:
    if archive.exists():
        raise SystemExit(f'Refusing to replace an existing archive: {archive}')

with zipfile.ZipFile(portable, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(app.rglob('*')):
        if path.is_file() and 'portable_config' not in path.relative_to(app).parts:
            archive.write(path, str(path.relative_to(dist)))

include_dirs = ['imageflow', 'tests', 'scripts', 'docs', 'licenses']
include_files = ['README.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE', '.gitignore', 'pyproject.toml',
                 'requirements.txt', 'requirements-dev.txt', 'run.py', 'run.cmd', 'ImageFlow.spec', 'AGENTS.md', 'PROJECT_STATE.md']
files = [root / name for name in include_files]
for name in include_dirs:
    files.extend(path for path in (root / name).rglob('*') if path.is_file() and '__pycache__' not in path.parts)
files.extend(path for path in (root / 'artifacts').glob('*') if path.is_file() and path.suffix in {'.png', '.xml', '.txt', '.json'})
files.extend((root / 'artifacts' / 'preview-benchmark').glob('*.json'))
for mode in ['offscreen', 'windows']:
    for name in ['smoke-result.json', 'packaged-window.png']:
        path = root / 'artifacts' / f'packaged-{mode}' / name
        if path.is_file():
            files.append(path)
with zipfile.ZipFile(source, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(files):
        archive.write(path, str(Path('ImageFlow') / path.relative_to(root)))

lines = []
for archive in [portable, source]:
    with zipfile.ZipFile(archive) as package:
        damaged = package.testzip()
        if damaged:
            raise RuntimeError(f'Archive checksum failure: {damaged}')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    lines.append(f'{digest}  {archive.name}')
    print(f'{archive.name}: {archive.stat().st_size / 1024 / 1024:.2f} MiB, SHA-256 {digest}')
(dist / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', 'ascii')
