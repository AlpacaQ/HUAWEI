"""只读取交付包：核验17个JPEG、字节、SHA256及公共坐标接口，不重新编码。"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image
from image_processing import tile_boxes, intersects, validate_roi


def verify(root):
    root = Path(root).resolve()
    index = json.loads((root / 'package_index.json').read_text(encoding='utf-8'))
    ids = [e['image_id'] for e in index['images']]
    assert len(ids) == len(set(ids)), '图片ID重复'
    assert index.get('image_count', len(ids)) == len(ids)
    assert index.get('transmission_jpeg_count', 17 * len(ids)) == 17 * len(ids)
    results = []
    for entry in index['images']:
        path = root / entry['manifest']
        m = json.loads(path.read_text(encoding='utf-8'))
        assert m['image_id'] == entry['image_id']
        roi = validate_roi(m['roi'], m['width'], m['height'])
        truth = json.loads((root / entry['ground_truth']).read_text(encoding='utf-8'))
        assert truth['image_id'] == m['image_id'] and truth['roi'] == roi
        assert truth['processed_size'] == [m['width'], m['height']]
        assert (root / entry['roi_preview']).is_file()
        if truth['human_confirmation']['status'] == 'unable_to_confirm':
            assert truth['value'] is None and truth['reading_text'] is None and truth['unit'] is None
        assert len(m['tiles']) == 16, '必须16块'
        records = [m['thumbnail']] + m['tiles']
        assert all(r['image_id'] == m['image_id'] for r in records)
        names = [r['payload'] for r in records]
        assert len(set(names)) == 17
        assert set(names) == {p.name for p in path.parent.glob('*.jpg')}
        for i, (t, box) in enumerate(zip(m['tiles'], tile_boxes(m['width'], m['height']))):
            assert t['tile_id'] == i and t['box'] == box
            assert [t['x'], t['y'], t['w'], t['h']] == [box[0], box[1], box[2]-box[0], box[3]-box[1]]
            assert t['priority'] == int(intersects(box, roi))
        total = 0
        for r in records:
            p = (path.parent / r['payload']).resolve()
            assert p.parent == path.parent.resolve(), 'payload越界'
            data = p.read_bytes()
            assert len(data) == r['size_bytes'], str(p)
            assert hashlib.sha256(data).hexdigest() == entry['payload_sha256'][r['payload']], str(p)
            with Image.open(p) as im:
                assert im.format == 'JPEG' and im.mode == 'RGB'
                expected = (r['width'], r['height']) if 'tile_id' not in r else (r['w'], r['h'])
                assert im.size == expected
                im.verify()
            total += len(data)
        assert total == m['total_size_bytes'] == entry['total_size_bytes']
        source = root / entry['source_file']
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry['source_sha256']
        results.append({'image_id': m['image_id'], 'jpeg_count': 17, 'total_size_bytes': total, 'verified': True})
    assert sum(r['total_size_bytes'] for r in results) == index['total_size_bytes']
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package_dir')
    args = parser.parse_args()
    print(json.dumps(verify(args.package_dir), ensure_ascii=False, indent=2))
