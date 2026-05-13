"""
Quick diagnostic: inspect image structure inside a GE Lunar XPS file.
Usage:  python3 debug_xps.py /path/to/file.xps
"""
import sys
import zipfile
import io
from PIL import Image

path = sys.argv[1] if len(sys.argv) > 1 else input("XPS path: ").strip()

IMAGE_EXTS = ('.PNG', '.JPG', '.JPEG', '.WDP', '.JXR', '.BMP', '.TIF', '.TIFF')

with zipfile.ZipFile(path) as zf:
    names = zf.namelist()

    # All image-like entries
    imgs = [n for n in names if any(n.upper().endswith(e) for e in IMAGE_EXTS)]
    print(f"\n=== {len(imgs)} image entries (PNG/JPG/WDP/JXR/BMP/TIF) ===")
    for n in sorted(imgs):
        data = zf.read(n)
        try:
            im = Image.open(io.BytesIO(data))
            print(f"  {n:70s}  {im.width}x{im.height}  mode={im.mode}")
        except Exception as e:
            print(f"  {n:70s}  {len(data)} bytes  (PIL cannot open: {e})")

    # All resource/image paths (catches unusual extensions)
    all_res = [n for n in names if 'Resource' in n or 'Image' in n]
    if all_res:
        print(f"\n=== All resource/image paths ({len(all_res)}) ===")
        for n in sorted(all_res):
            info = zf.getinfo(n)
            print(f"  {n:70s}  {info.file_size:>8} bytes")

    # Pages
    pages = sorted({n.split('/')[1] for n in names if n.startswith('Documents/')})
    print(f"\n=== Document pages: {pages} ===")

    # Full namelist
    print(f"\n=== Full namelist ({len(names)} entries) ===")
    for n in sorted(names):
        info = zf.getinfo(n)
        print(f"  {info.file_size:>9} bytes  {n}")
