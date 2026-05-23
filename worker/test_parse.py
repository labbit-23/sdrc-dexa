import sys
sys.path.insert(0, '/opt/sdrc/sdrc-dexa-worker/worker')
from parse_xps import _parse_region_bounds_by_position, extract_scan_images, extract_osteo_images

xps = '/mnt/ge-lunar/shared/dexa-reports/9304.xps'
print("=== BOUNDS ===")
r = _parse_region_bounds_by_position(xps)
for k, v in r.items():
    print(f"  {k}: y={v[1]:.0f}-{v[3]:.0f}")

print("=== PLAIN IMAGES (extract_scan_images) ===")
imgs = extract_scan_images(xps)
for k, img in imgs.items():
    print(f"  {k}: {img.size}")

print("=== PIPELINE PATH (extract_osteo_images — same as UI) ===")
imgs2 = extract_osteo_images(spine_xps=xps, left_femur_xps=xps, right_femur_xps=xps)
for k, img in imgs2.items():
    print(f"  {k}: {img.size}")
