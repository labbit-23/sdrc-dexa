import sys
sys.path.insert(0, '/opt/sdrc/sdrc-dexa-worker/worker')
from parse_xps import _parse_region_bounds_by_position, extract_scan_images

xps = '/mnt/ge-lunar/shared/dexa-reports/9304.xps'
print("=== BOUNDS ===")
r = _parse_region_bounds_by_position(xps)
for k, v in r.items():
    print(f"  {k}: y={v[1]:.0f}-{v[3]:.0f}")

print("=== PLAIN IMAGES ===")
imgs = extract_scan_images(xps)
for k, img in imgs.items():
    print(f"  {k}: {img.size}")
