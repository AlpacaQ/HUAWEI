"""A组整图JPEG：复用B/C预处理，独立输出，不再次编码已有交付文件。"""
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from PIL import Image
from image_processing import load_processed_image, TILE_QUALITY


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare_full_image(image_path, image_id, output_dir, expected_size=None):
    """返回manifest_A.json绝对路径；输出目录须为空或不存在。"""
    output = Path(output_dir).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('A组输出目录必须为空或不存在；禁止覆盖已有文件')
    started = perf_counter()
    image = load_processed_image(image_path)
    if expected_size is not None and list(image.size) != list(expected_size):
        raise ValueError(f'{image_id}: 处理后尺寸{image.size}与B/C清单不一致')
    output.mkdir(parents=True, exist_ok=True)
    payload = output / 'full.jpg'
    image.save(payload, format='JPEG', quality=TILE_QUALITY)
    size_bytes = payload.stat().st_size
    seconds = perf_counter() - started
    manifest = {
        'schema_version': 1, 'group': 'A', 'image_id': image_id,
        'source_name': Path(image_path).name, 'source_sha256': sha256(image_path),
        'payload': 'full.jpg', 'width': image.width, 'height': image.height,
        'mode': 'RGB', 'quality': TILE_QUALITY, 'size_bytes': size_bytes,
        'total_size_bytes': size_bytes, 'payload_sha256': sha256(payload),
        'image_processing_seconds': seconds,
        'processing_time_scope': 'starts before source read; includes EXIF transpose, RGB conversion, output directory creation, full JPEG encoding/write and size read; excludes SHA256, manifest write, verification and packaging',
        'preprocessing': 'image_processing.load_processed_image: EXIF transpose then RGB; no resize; metadata cleared',
        'payload_path_base': 'directory containing manifest_A.json',
    }
    path = output / 'manifest_A.json'
    write_json(path, manifest)
    return str(path)


def snapshot(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): sha256(p) for p in root.rglob('*') if p.is_file()}


def verify_full_package(package_dir, bc_package):
    root = Path(package_dir).resolve()
    bc = Path(bc_package).resolve()
    index = json.loads((root / 'package_index_A.json').read_text(encoding='utf-8'))
    bc_index = json.loads((bc / 'package_index.json').read_text(encoding='utf-8'))
    entries = {e['image_id']: e for e in bc_index['images']}
    if len(index['images']) != len(entries) or {e['image_id'] for e in index['images']} != set(entries):
        raise ValueError('A组图片集合与B/C不一致')
    results = []
    for entry in index['images']:
        manifest_path = root / entry['manifest']
        m = json.loads(manifest_path.read_text(encoding='utf-8'))
        source_entry = entries[entry['image_id']]
        bc_manifest = json.loads((bc / source_entry['manifest']).read_text(encoding='utf-8'))
        payload = (manifest_path.parent / m['payload']).resolve()
        if payload.parent != manifest_path.parent.resolve() or m['payload'] != 'full.jpg':
            raise ValueError('A组payload路径无效')
        if m['image_id'] != entry['image_id'] or m['quality'] != TILE_QUALITY or m['group'] != 'A':
            raise ValueError('A组编号或质量不一致')
        if [m['width'], m['height']] != [bc_manifest['width'], bc_manifest['height']]:
            raise ValueError('A组尺寸与B/C不一致')
        if sha256(bc / source_entry['source_file']) != m['source_sha256'] or m['source_sha256'] != source_entry['source_sha256']:
            raise ValueError('A组使用的原图与交接原图不一致')
        if payload.stat().st_size != m['size_bytes'] or m['total_size_bytes'] != m['size_bytes']:
            raise ValueError('A组实际字节数与清单不一致')
        if sha256(payload) != m['payload_sha256']:
            raise ValueError('A组JPEG内容发生变化')
        with Image.open(payload) as decoded:
            decoded.load()  # 完整解码，不能只验证文件头。
            if decoded.format != 'JPEG' or decoded.mode != 'RGB' or decoded.size != (m['width'], m['height']):
                raise ValueError('A组JPEG尺寸、模式或格式无效')
            if decoded.getexif().get(274, 1) != 1:
                raise ValueError('A组不能携带再次旋转的EXIF朝向')
        results.append({'image_id': m['image_id'], 'jpeg_opened': True,
                        'size_matches_BC': True, 'size_bytes': m['size_bytes'], 'bytes_verified': True})
    if sum(r['size_bytes'] for r in results) != index['total_size_bytes']:
        raise ValueError('A组总字节数错误')
    return results


def build_full_package(bc_package, output_dir):
    bc = Path(bc_package).resolve()
    output = Path(output_dir).resolve()
    if output == bc or bc in output.parents or output in bc.parents:
        raise ValueError('A组目录必须独立于B/C包，不能覆盖或嵌套')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('A组输出根目录必须为空或不存在；重跑请换目录')
    index = json.loads((bc / 'package_index.json').read_text(encoding='utf-8'))
    before = snapshot(bc)
    # 先检查全部输入，再开始编码，避免输入错误产生半批结果。
    inputs = []
    for e in index['images']:
        source = bc / e['source_file']
        m = json.loads((bc / e['manifest']).read_text(encoding='utf-8'))
        if sha256(source) != e['source_sha256']:
            raise ValueError(f"{e['image_id']}: 原图SHA256与交接包不一致")
        if Path(e['image_id']).name != e['image_id'] or e['image_id'] in ('.', '..'):
            raise ValueError('图片编号不能包含路径')
        inputs.append((e['image_id'], source, [m['width'], m['height']]))
    images = []
    for image_id, source, size in inputs:
        path = Path(prepare_full_image(source, image_id, output / image_id, size))
        m = json.loads(path.read_text(encoding='utf-8'))
        images.append({'image_id': image_id, 'manifest': path.relative_to(output).as_posix(),
                       'payload': f'{image_id}/full.jpg', 'size_bytes': m['size_bytes']})
    write_json(output / 'package_index_A.json', {'schema_version': 1, 'group': 'A',
        'image_count': len(images), 'quality': TILE_QUALITY, 'images': images,
        'total_size_bytes': sum(e['size_bytes'] for e in images),
        'path_base': 'package_index_A.json directory; each manifest payload is relative to its own directory'})
    results = verify_full_package(output, bc)
    if snapshot(bc) != before:
        raise RuntimeError('B/C包内容改变，验收失败')
    report = {'images': results, 'bc_files_unchanged': True,
              'bc_snapshot_sha256': before, 'total_size_bytes': sum(e['size_bytes'] for e in images)}
    write_json(output / 'verification_A.json', report)
    return output / 'package_index_A.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bc-package', default='delivery_v2')
    parser.add_argument('--output-dir', default='delivery_A_v1')
    parser.add_argument('--verify-only', action='store_true', help='只打开已有JPEG验收，不重新编码')
    args = parser.parse_args()
    try:
        if args.verify_only:
            print(json.dumps(verify_full_package(args.output_dir, args.bc_package), ensure_ascii=False, indent=2))
        else:
            print(build_full_package(args.bc_package, args.output_dir))
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        parser.exit(1, f'A组处理失败：{exc}\n')


if __name__ == '__main__':
    main()
