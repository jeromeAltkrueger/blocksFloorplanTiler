"""
COORDINATE TRANSFORMATION ANALYSIS
===================================
Trace the ENTIRE pipeline: PDF -> Image -> Tiles -> Leaflet -> back to PDF

PIPELINE:
  1. PDF -> Image:  pixel = pdf_pt * pdf_scale  (fitz.Matrix(pdf_scale, pdf_scale))
  2. Image -> Leaflet:  lng = pixel_x / 2^maxZoom,  lat = -pixel_y / 2^maxZoom
  3. Leaflet -> Image:  pixel_x = lng * 2^maxZoom,  pixel_y = -lat * 2^maxZoom
  4. Image -> PDF:  pdf_pt = pixel / pdf_scale

FORMULA:
  pdf_x = leaflet_x * 2^maxZoom / pdf_scale
  pdf_y = (-leaflet_y) * 2^maxZoom / pdf_scale

NOTE: User's reference rect [2829.4, 888.774, 3351.04, 1233.55] is in STANDARD
PDF coords (bottom-left origin, Y up). PyMuPDF uses top-left origin (Y down).
We validate by converting our PyMuPDF coords to standard coords for comparison.
"""

pdf_scale = 6.110478508644631
img_width = 20595
img_height = 14567
max_zoom = 10

scale = 2 ** max_zoom  # 1024
page_width_pt = img_width / pdf_scale
page_height_pt = img_height / pdf_scale

print("=" * 80)
print("SETUP")
print("=" * 80)
print(f"pdf_scale = {pdf_scale}")
print(f"Image: {img_width} x {img_height} px")
print(f"PDF page (PyMuPDF): {page_width_pt:.2f} x {page_height_pt:.2f} pt")
print(f"Leaflet scale: 2^{max_zoom} = {scale}")
print()

# User's example
leaflet_west, leaflet_east = 16.890625, 20
leaflet_north, leaflet_south = -6.859375, -8.890625
std_pdf_rect = [2829.4, 888.774, 3351.04, 1233.55]  # standard PDF coords

print("=" * 80)
print("PyMuPDF COORDINATES (top-left origin, Y down)")
print("=" * 80)

corners = [
    ("NW", leaflet_west, leaflet_north),
    ("NE", leaflet_east, leaflet_north),
    ("SE", leaflet_east, leaflet_south),
    ("SW", leaflet_west, leaflet_south),
]

for name, lx, ly in corners:
    pdf_x = lx * scale / pdf_scale
    pdf_y = (-ly) * scale / pdf_scale
    print(f"  {name}: Leaflet ({lx:>10.6f}, {ly:>10.6f}) -> PDF ({pdf_x:>8.2f}, {pdf_y:>8.2f})")

pymupdf_x0 = leaflet_west * scale / pdf_scale
pymupdf_y0 = (-leaflet_north) * scale / pdf_scale  # north = top = smaller Y
pymupdf_x1 = leaflet_east * scale / pdf_scale
pymupdf_y1 = (-leaflet_south) * scale / pdf_scale   # south = bottom = larger Y

print(f"\nPyMuPDF Rect: ({pymupdf_x0:.2f}, {pymupdf_y0:.2f}, {pymupdf_x1:.2f}, {pymupdf_y1:.2f})")
print(f"  Position: {pymupdf_x0/page_width_pt*100:.0f}%-{pymupdf_x1/page_width_pt*100:.0f}% across, "
      f"{pymupdf_y0/page_height_pt*100:.0f}%-{pymupdf_y1/page_height_pt*100:.0f}% down")
print()

print("=" * 80)
print("CROSS-VALIDATE vs User's Standard PDF Rect")
print("=" * 80)

# Convert PyMuPDF (top-left) to standard PDF (bottom-left) for comparison
std_x0 = pymupdf_x0
std_y0 = page_height_pt - pymupdf_y1  # south edge -> smaller standard Y
std_x1 = pymupdf_x1
std_y1 = page_height_pt - pymupdf_y0  # north edge -> larger standard Y

print(f"  Computed (std PDF): [{std_x0:.2f}, {std_y0:.2f}, {std_x1:.2f}, {std_y1:.2f}]")
print(f"  Expected (user):   [{std_pdf_rect[0]}, {std_pdf_rect[1]}, {std_pdf_rect[2]}, {std_pdf_rect[3]}]")

diffs = [abs(std_x0 - std_pdf_rect[0]), abs(std_y0 - std_pdf_rect[1]),
         abs(std_x1 - std_pdf_rect[2]), abs(std_y1 - std_pdf_rect[3])]
print(f"  Differences:       [{diffs[0]:.2f}, {diffs[1]:.2f}, {diffs[2]:.2f}, {diffs[3]:.2f}] pt")
print(f"  Max diff: {max(diffs):.2f} pt ({max(diffs)/max(page_width_pt, page_height_pt)*100:.3f}% of page)")

all_ok = all(d < 10 for d in diffs)
print(f"\n  {'MATCH' if all_ok else 'MISMATCH'} (within 10pt tolerance)")
print(f"  Small diffs from int() rounding in rendering + whitespace trimming")
print()

print("=" * 80)
print("FINAL FORMULA")
print("=" * 80)
print()
print("  pdf_x = leaflet_x * 2^maxZoom / pdf_scale")
print("  pdf_y = (-leaflet_y) * 2^maxZoom / pdf_scale")
print()
print("  scale = 2^maxZoom  (Leaflet CRS.Simple unproject)")
print("  pdf_scale = metadata.quality_settings.pdf_scale")
print("  tile_size is NOT part of the formula")
print("  NO Y-flip needed (PyMuPDF + pixels both use top-left origin)")
print("=" * 80)
