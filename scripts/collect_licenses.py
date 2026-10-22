"""Copy installed dependency license resources into a distributable directory."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

target = Path(sys.argv[1])
root = Path(__file__).resolve().parent.parent
for source in (root / 'licenses').glob('*'):
    if source.is_file():
        shutil.copyfile(source, target / source.name)
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.is_file():
    shutil.copyfile(python_license, target / 'Python-LICENSE.txt')
for package in ['PySide6_Essentials', 'shiboken6', 'Pillow', 'pyinstaller']:
    dist = distribution(package)
    copied = 0
    for item in dist.files or []:
        if any(part.lower() in {'licenses', 'license_files'} for part in item.parts) or item.name.lower().startswith(('license', 'copying')):
            source = Path(dist.locate_file(item))
            if source.is_file():
                destination = target / package / Path(*[part for part in item.parts if part not in {'.', '..'}])
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                copied += 1
    if copied == 0:
        print(f'No bundled license files found for {package}; see THIRD_PARTY_NOTICES.md')
print(f'Licenses copied to {target}')
