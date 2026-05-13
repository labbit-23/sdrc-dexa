"""
Quick diagnostic: inspect image structure inside a GE Lunar XPS file.
Usage:  python3 debug_xps.py /path/to/file.xps
"""
import sys
import zipfile
import io
from PIL import Image

path = sys.argv[1] if len(sys.argv) > 1 else input("XPS path: ").strip()

with zipfile.ZipFile(path) as zf:
    names = zf.namelist()

    # All image entries
    imgs = [n for n in names if n.upper().endswith('.PNG')]
    print(f"\n=== {len(imgs)} PNG entries ===")
    for n in sorted(imgs):
        try:
            data = zf.read(n)
            im = Image.open(io.BytesIO(data))
            print(f"  {n:60s}  {im.width}x{im.height}  mode={im.mode}")
        except Exception as e:
            print(f"  {n}  ERROR: {e}")

    # Pages present
    pages = sorted({n.split('/')[1] for n in names if n.startswith('Documents/')})
    print(f"\n=== Document pages: {pages} ===")

    # Resources per page
    for page in pages:
        page_imgs = [n for n in imgs if n.startswith(f'Documents/{page}/')]
        if page_imgs:
            print(f"  Page {page}: {len(page_imgs)} images")
