"""将已有A组JPEG打包，不重新编码；从inspection_image运行。"""
import shutil
import tempfile
import zipfile
from pathlib import Path
from image_processing_A import sha256, verify_full_package


if __name__ == '__main__':
    base = Path(__file__).resolve().parent
    root = base / 'delivery_A_v1'
    verify_full_package(root, base / 'delivery_v2')
    for name in ['README_A.md', 'image_processing_A.py', 'image_processing.py', 'requirements.txt']:
        shutil.copyfile(base / name, root / name)
    archive = base / 'inspection_image_delivery_A_v1.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
        for p in sorted(root.rglob('*')):
            if p.is_file():
                z.write(p, 'delivery_A_v1/' + p.relative_to(root).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('ZIP损坏')
        with tempfile.TemporaryDirectory() as temp:
            z.extractall(temp)
            verify_full_package(Path(temp) / 'delivery_A_v1', base / 'delivery_v2')
    archive.with_suffix('.zip.sha256').write_text(sha256(archive) + '  ' + archive.name + '\n', encoding='ascii')
    print(archive)
