"""
PDF Annotation Module
Handles annotating PDFs with shapes and markers.
"""

import io
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("pdf_annotation")

import azure.functions as func
import fitz  # PyMuPDF for PDF annotation
import httpx
from azure.storage.blob import BlobServiceClient, ContentSettings
from PIL import Image, ImageChops

# ==========================================
# PDF ANNOTATION CONFIGURATION
# ==========================================

# Annotation styling
ANNOTATION_CONFIG = {
    "polygon": {
        "fill_color": (1, 0, 0),
        "fill_opacity": 0.25,
        "stroke_color": None,
        "stroke_width": 0,
        "stroke_opacity": 0.0
    },
    "marker": {
        "fill_color": (1, 1, 0),
        "fill_opacity": 0.8,
        "radius": 10,
        "stroke_color": (0, 0, 0),
        "stroke_width": 2
    },
    "square": {
        "fill_color": (1, 0, 0),
        "fill_opacity": 0.4,
        "stroke_color": (0.8, 0, 0),
        "stroke_width": 3,
        "stroke_opacity": 1.0
    },
    "text": {
        "font_size": 14,
        "font_color": (1, 0, 0),
        "background_color": (1, 1, 1),
        "background_opacity": 0.9,
        "padding": 4
    }
}


# ==========================================
# COORDINATE TRANSFORMATION
# ==========================================
#
# Forward pipeline (tile generation in app.py):
#   1. PDF → Image:  pixel = pdf_pt × pdf_scale        (fitz.Matrix)
#   2. Trim whitespace: crops margins, shifts origin     (trim_whitespace)
#   3. Image → Leaflet:  lng = pixel_x / 2^maxZoom      (CRS.Simple)
#                         lat = -pixel_y / 2^maxZoom
#
# Reverse pipeline (what we need for annotations):
#   1. Leaflet → trimmed image pixels
#   2. Add trim offset → original (pre-trim) image pixels
#   3. Divide by pdf_scale → PDF points
#
# Formula:
#   pdf_x = (leaflet_x × 2^maxZoom + trim_left) / pdf_scale
#   pdf_y = (-leaflet_y × 2^maxZoom + trim_top) / pdf_scale
#
# When no trimming occurred: trim_left=0, trim_top=0, simplifies to old formula
# ==========================================

def detect_trim_offset(page: fitz.Page, metadata: Dict[str, Any]) -> Tuple[float, float]:
    """
    Detect the whitespace trim offset by comparing PDF page dimensions
    with the stored image dimensions. If trimming occurred, re-render at
    low resolution to find the exact content origin.

    Uses the same logic as trim_whitespace() in app.py:
    - bg_color=(255,255,255), tolerance=10, padding=20 pixels

    Args:
        page: PyMuPDF page object (original PDF)
        metadata: Metadata with source_image dimensions and pdf_scale

    Returns:
        (trim_left, trim_top) in pixels at pdf_scale resolution.
        These are the pixel offsets that were cropped from the pre-trim image.
    """
    pdf_scale = metadata["quality_settings"]["pdf_scale"]
    img_w = metadata["source_image"]["width"]
    img_h = metadata["source_image"]["height"]

    # Pre-trim image dimensions
    pretrim_w = page.rect.width * pdf_scale
    pretrim_h = page.rect.height * pdf_scale

    # Check if trimming occurred (allow 1px tolerance for rounding)
    if abs(pretrim_w - img_w) <= 1 and abs(pretrim_h - img_h) <= 1:
        logger.info("No whitespace trimming detected — using direct formula")
        return (0.0, 0.0)

    logger.info(f"Whitespace trimming detected!")
    logger.info(f"  Pre-trim:  {pretrim_w:.0f} x {pretrim_h:.0f} px")
    logger.info(f"  Post-trim: {img_w} x {img_h} px")
    logger.info(f"  Trimmed:   {pretrim_w - img_w:.0f} x {pretrim_h - img_h:.0f} px")

    # Re-render at low resolution to detect content bbox
    # Use scale 2.0 (144 DPI) — fast and accurate enough for bbox detection
    detect_scale = 2.0
    pix = page.get_pixmap(matrix=fitz.Matrix(detect_scale, detect_scale), alpha=False)
    pil_img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

    # Same detection logic as trim_whitespace in app.py
    bg = Image.new("RGB", pil_img.size, (255, 255, 255))
    diff = ImageChops.difference(pil_img, bg).convert("L")
    mask = diff.point(lambda p: 255 if p > 10 else 0)  # tolerance=10
    bbox = mask.getbbox()

    pil_img.close()

    if not bbox:
        logger.warning("Could not detect content bbox — using (0, 0) offset")
        return (0.0, 0.0)

    # bbox is (left, top, right, bottom) in detect_scale pixels
    # Apply same padding as trim_whitespace: 20 pixels at pdf_scale
    # At detect_scale, padding = 20 * detect_scale / pdf_scale
    padding_at_detect = 20 * detect_scale / pdf_scale

    left_detect = max(0, bbox[0] - padding_at_detect)
    top_detect = max(0, bbox[1] - padding_at_detect)

    # Convert from detect_scale pixels to pdf_scale pixels
    trim_left = left_detect * pdf_scale / detect_scale
    trim_top = top_detect * pdf_scale / detect_scale

    logger.info(f"  Content bbox at {detect_scale}x: left={bbox[0]}, top={bbox[1]}")
    logger.info(f"  Trim offset (at pdf_scale): left={trim_left:.1f}, top={trim_top:.1f} px")

    # Verify: post-trim dimensions should roughly match metadata
    right_detect = min(pix.width, bbox[2] + padding_at_detect)
    bottom_detect = min(pix.height, bbox[3] + padding_at_detect)
    detected_w = (right_detect - left_detect) * pdf_scale / detect_scale
    detected_h = (bottom_detect - top_detect) * pdf_scale / detect_scale
    logger.info(f"  Detected content size: {detected_w:.0f} x {detected_h:.0f} px (metadata: {img_w} x {img_h})")

    return (trim_left, trim_top)


def transform_coords(leaflet_coords: List[float], metadata: Dict[str, Any],
                     trim_offset: Tuple[float, float] = (0.0, 0.0)) -> Tuple[float, float]:
    """
    Transform Leaflet CRS.Simple coordinates to PyMuPDF PDF coordinates.

    Args:
        leaflet_coords: [x, y] where x=lng (positive), y=lat (negative)
        metadata: Must contain 'max_zoom' and 'quality_settings.pdf_scale'
        trim_offset: (trim_left, trim_top) in pixels at pdf_scale resolution

    Returns:
        (pdf_x, pdf_y) in PyMuPDF coordinate space (top-left origin, Y down)
    """
    x, y = leaflet_coords
    scale = 2 ** metadata["max_zoom"]
    pdf_scale = metadata["quality_settings"]["pdf_scale"]
    trim_left, trim_top = trim_offset

    # Leaflet → trimmed image pixels → pre-trim image pixels → PDF points
    pdf_x = (x * scale + trim_left) / pdf_scale
    pdf_y = (-y * scale + trim_top) / pdf_scale

    return (pdf_x, pdf_y)


def draw_polygon_on_pdf(page: fitz.Page, coordinates: List[List[List[float]]],
                       metadata: Dict[str, Any], config: Dict[str, Any],
                       overlay: str = None,
                       trim_offset: Tuple[float, float] = (0.0, 0.0),
                       pending_callouts: List = None,
                       shape_rects: List = None,
                       polygon_rects: List = None) -> None:
    """
    Draw a filled polygon on the PDF page, optionally with centered overlay text.

    Args:
        page: PyMuPDF page object
        coordinates: GeoJSON polygon coordinates [[[x, y], [x, y], ...]]
        metadata: Metadata for coordinate transformation
        config: Styling configuration
        overlay: Optional text to display at the polygon's centroid
        trim_offset: (trim_left, trim_top) whitespace offset in pixels
        pending_callouts: Mutable list; if an overlay is set, a
            (cx, cy, circumradius, text) tuple is appended so the caller
            can place the Callout annotation after all shapes are burned in.
    """
    # GeoJSON polygons: coordinates[0] is outer ring
    outer_ring = coordinates[0]

    logger.info(f"Drawing polygon with {len(outer_ring)} points")

    # Convert coords to PDF coordinates
    pdf_points = []
    for point in outer_ring:
        x, y = point[0], point[1]
        logger.info(f"  Leaflet: [{x}, {y}]")
        x_pdf, y_pdf = transform_coords([x, y], metadata, trim_offset)
        logger.info(f"  -> PDF: [{x_pdf:.2f}, {y_pdf:.2f}]")
        pdf_points.append(fitz.Point(x_pdf, y_pdf))

    if len(pdf_points) >= 3:
        # draw_polyline + closePath=True is the correct API for filled closed
        # polygons in PyMuPDF 1.23.x (Shape.draw_polygon does not exist)
        shape = page.new_shape()
        shape.draw_polyline(pdf_points)
        shape.finish(
            fill=config["fill_color"],
            color=config["stroke_color"],
            width=config["stroke_width"],
            fill_opacity=config["fill_opacity"],
            stroke_opacity=config.get("stroke_opacity", 0.0),
            closePath=True
        )
        shape.commit()
        logger.info(f"✅ Polygon drawn with {len(pdf_points)} points")

        # Register bounding box so callout placement avoids the polygon fill.
        if shape_rects is not None:
            xs = [p.x for p in pdf_points]
            ys = [p.y for p in pdf_points]
            poly_bbox = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
            shape_rects.append(poly_bbox)
            # Also track in the hard-exclusion list so callouts from OTHER
            # markers are never placed on top of this polygon's fill area.
            if polygon_rects is not None:
                polygon_rects.append(poly_bbox)

        # Queue a deferred callout whose arrow tip points at the polygon centroid.
        # Use circumradius (max centroid→vertex distance) so the text box is
        # placed beyond the polygon's outermost vertex in every direction.
        if overlay and pending_callouts is not None:
            cx = sum(p.x for p in pdf_points) / len(pdf_points)
            cy = sum(p.y for p in pdf_points) / len(pdf_points)
            circumradius = max(
                ((p.x - cx) ** 2 + (p.y - cy) ** 2) ** 0.5
                for p in pdf_points
            )
            pending_callouts.append((cx, cy, circumradius, overlay, pdf_points))
            logger.info(f"   Polygon overlay queued: centroid=({cx:.1f},{cy:.1f}), circumradius={circumradius:.1f}")
    else:
        logger.warning(f"⚠️  Not enough points: {len(pdf_points)}")


def draw_marker_on_pdf(page: fitz.Page, coordinates: List[float],
                       metadata: Dict[str, Any], config: Dict[str, Any],
                       label: str = None,
                       overlay: str = None,
                       trim_offset: Tuple[float, float] = (0.0, 0.0),
                       pending_callouts: List = None,
                       shape_rects: List = None) -> None:
    """
    Draw a circular marker (burned into content stream) on the PDF page.

    If an overlay string is provided it is NOT rendered inline — instead a
    (x_pdf, y_pdf, radius, text) tuple is appended to pending_callouts so that
    the caller can place a Callout annotation after all shapes are drawn.

    Args:
        page: PyMuPDF page object
        coordinates: [x, y] point coordinates
        metadata: Metadata for coordinate transformation
        config: Styling configuration
        label: Optional text label burned below the marker
        overlay: Optional overlay text — emitted as a Callout annotation via pending_callouts
        trim_offset: (trim_left, trim_top) whitespace offset in pixels
        pending_callouts: Mutable list; (x_pdf, y_pdf, radius, text) appended when overlay present
    """
    x, y = coordinates[0], coordinates[1]
    logger.info(f"Drawing marker at [{x}, {y}]")

    # Convert to PDF coordinates
    x_pdf, y_pdf = transform_coords([x, y], metadata, trim_offset)
    radius = config["radius"]

    # Native PDF Circle annotation — selectable/movable in Acrobat
    stroke_color = config.get("stroke_color", (0, 0, 0))
    circ_rect = fitz.Rect(
        x_pdf - radius, y_pdf - radius,
        x_pdf + radius, y_pdf + radius
    )
    circ_annot = page.add_circle_annot(circ_rect)
    circ_annot.set_colors(stroke=stroke_color, fill=config["fill_color"])
    circ_annot.set_border(width=config.get("stroke_width", 2))
    circ_annot.update(opacity=config["fill_opacity"])
    logger.info(f"✅ Marker circle annotation placed at ({x_pdf:.1f}, {y_pdf:.1f})")
    if shape_rects is not None:
        shape_rects.append(circ_rect)

    # Both label and overlay become separate Callout annotations, each with
    # their own arrow pointing at the marker centre.
    if pending_callouts is not None:
        if label:
            pending_callouts.append((x_pdf, y_pdf, radius, label))
            logger.info(f"   Label queued for callout: '{label}'")
        if overlay:
            pending_callouts.append((x_pdf, y_pdf, radius, overlay))
            logger.info(f"   Overlay queued for callout: '{overlay}'")
    else:
        if label or overlay:
            logger.warning("   label/overlay present but no pending_callouts list provided — skipped")


def draw_square_on_pdf(page: fitz.Page, coordinates: List[List[List[float]]],
                      metadata: Dict[str, Any], config: Dict[str, Any],
                      overlay: str = None,
                      trim_offset: Tuple[float, float] = (0.0, 0.0)) -> None:
    """
    Draw a filled square/rectangle on the PDF page, optionally with centered overlay text.

    Args:
        page: PyMuPDF page object
        coordinates: Rectangle coordinates (4 corner points)
        metadata: Metadata for coordinate transformation
        config: Styling configuration
        overlay: Optional text to display at the polygon's centroid
        trim_offset: (trim_left, trim_top) whitespace offset in pixels
    """
    # Treat squares the same as polygons
    draw_polygon_on_pdf(page, coordinates, metadata, config, overlay, trim_offset)


def draw_text_on_pdf(page: fitz.Page, position: List[float],
                     text: str, config: Dict[str, Any]) -> None:
    """
    Draw text with background on the PDF page.

    Args:
        page: PyMuPDF page object
        position: [x, y] position in PDF coordinates
        text: Text content to draw
        config: Text styling configuration
    """
    x, y = position
    font_size = config["font_size"]
    padding = config["padding"]

    # Estimate text width (rough approximation)
    text_width = len(text) * font_size * 0.6
    text_height = font_size

    # Draw background rectangle
    rect = fitz.Rect(
        x - padding,
        y - padding,
        x + text_width + padding,
        y + text_height + padding
    )

    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(
        fill=config["background_color"],
        fill_opacity=config["background_opacity"]
    )
    shape.commit()

    # Draw text
    page.insert_text(
        fitz.Point(x, y + font_size),  # Baseline position
        text,
        fontsize=font_size,
        color=config["font_color"]
    )


def _closest_point_on_polygon(query: fitz.Point, pts: List[fitz.Point]) -> fitz.Point:
    """
    Return the closest point on a polygon's perimeter to `query`.

    Iterates every edge of the outer ring using the perpendicular-foot formula,
    clamped to the segment endpoints.  Deduplicates the GeoJSON closing vertex
    (where pts[0] == pts[-1]) before iterating so there is no zero-length edge.
    """
    # Remove duplicate GeoJSON closing vertex
    ring = pts
    if len(ring) > 1 and ring[0].x == ring[-1].x and ring[0].y == ring[-1].y:
        ring = ring[:-1]

    best_pt = ring[0]
    best_d2 = float("inf")
    n = len(ring)
    for i in range(n):
        a = ring[i]
        b = ring[(i + 1) % n]
        dx, dy = b.x - a.x, b.y - a.y
        len2 = dx * dx + dy * dy
        if len2 == 0.0:
            cp = a
        else:
            t = max(0.0, min(1.0, ((query.x - a.x) * dx + (query.y - a.y) * dy) / len2))
            cp = fitz.Point(a.x + t * dx, a.y + t * dy)
        d2 = (cp.x - query.x) ** 2 + (cp.y - query.y) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_pt = cp
    return best_pt


def _segments_intersect(p1: fitz.Point, p2: fitz.Point,
                       p3: fitz.Point, p4: fitz.Point) -> bool:
    """
    Return True if segment p1-p2 and segment p3-p4 properly cross each other.

    Uses the cross-product orientation test.  Collinear / touching-endpoint
    cases return False intentionally: leader lines fanning out from nearby
    anchors often share a near-common origin and we don't want to penalise that.
    """
    def _cross(o: fitz.Point, a: fitz.Point, b: fitz.Point) -> float:
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)

    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    return (((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and
            ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)))


def _segment_intersects_rect(p1: fitz.Point, p2: fitz.Point,
                             rect: fitz.Rect) -> bool:
    """Return True if line segment p1-p2 passes through or touches *rect*.

    Checks:
      1. Either endpoint inside the rect → True.
      2. Segment crosses any of the 4 rect edges → True.
    """
    if rect.contains(p1) or rect.contains(p2):
        return True
    corners = [
        (fitz.Point(rect.x0, rect.y0), fitz.Point(rect.x1, rect.y0)),  # top
        (fitz.Point(rect.x1, rect.y0), fitz.Point(rect.x1, rect.y1)),  # right
        (fitz.Point(rect.x1, rect.y1), fitz.Point(rect.x0, rect.y1)),  # bottom
        (fitz.Point(rect.x0, rect.y1), fitz.Point(rect.x0, rect.y0)),  # left
    ]
    for c1, c2 in corners:
        if _segments_intersect(p1, p2, c1, c2):
            return True
    return False


def place_callout_annotation(
        page: fitz.Page,
        marker_x: float,
        marker_y: float,
        marker_radius: float,
        text: str,
        placed_boxes: List[fitz.Rect],
        font_size: float = 10.0,
        max_box_width: float = 200.0,
        gap: float = 15.0,
        polygon_points: List[fitz.Point] = None,
        forbidden_rects: List[fitz.Rect] = None,
        committed_lines: List[Tuple[fitz.Point, fitz.Point]] = None,
        marker_zones: List[fitz.Rect] = None) -> None:
    """
    Add a Callout FreeText annotation.

    For markers the arrow tip is the marker centre.  For polygons, after the
    text box position is decided, the tip is snapped to the closest point on
    the polygon's perimeter to the box-border attach point — so the arrow
    always touches the polygon edge rather than piercing through the fill.

    The text box is placed outside the shape with a minimum gap equal to
    marker_radius + gap points.  Eight candidate directions are tried in order;
    the position with the least overlap against already-placed callout boxes is
    chosen (zero-overlap preferred).  A crossing penalty is added for each
    already-committed leader line the proposed line would cross.  The chosen
    rect is appended to placed_boxes so subsequent calls avoid it.

    Args:
        page:             PyMuPDF page object.
        marker_x/y:       Anchor point in PDF points used for box placement
                          (marker centre or polygon centroid).
        marker_radius:    Exclusion radius around the anchor (circle radius for
                          markers, circumradius for polygons).
        text:             Text to display in the callout box.
        placed_boxes:     Mutable list of already-placed Rect objects.
        font_size:        Font size for the callout text.
        box_width:        Fixed width for the text box in points.
        gap:              Minimum clearance beyond marker_radius to box edge.
        polygon_points:   If provided, the arrow tip is snapped to the closest
                          point on this polygon's outer-ring perimeter instead
                          of the anchor point.  Pass None for circular markers.
        committed_lines:  Already-drawn leader lines as (attach, tip) pairs.
                          Each crossing adds a large penalty so the optimiser
                          strongly prefers non-crossing placements.
    """
    page_rect = page.rect

    # ── Auto-size box width to text content ───────────────────────────────────
    # Measure natural single-line width, then decide how many lines to wrap into.
    CHAR_W = font_size * 0.65  # bold Helvetica avg char width
    natural_width = len(text) * CHAR_W + 10  # single-line width + padding

    # Target: 1-2 lines for short text, up to 3 lines for long text
    if natural_width <= max_box_width:
        box_width = min(max_box_width, max(natural_width, font_size * 4))  # at least 4 chars wide
    else:
        # Wrap into 2 lines first, 3 if still too wide
        box_width = min(max_box_width, max(natural_width / 2 + 10, font_size * 6))
        if box_width > max_box_width:
            box_width = min(max_box_width, natural_width / 3 + 10)
    box_width = round(box_width)

    # ── Sizing diagnostics (inputs) ───────────────────────────────────────────
    logger.info(
        f"   [sizing-in]  text='{text}' | chars={len(text)}"
        f" | page={page_rect.width:.0f}x{page_rect.height:.0f}pt"
        f" | radius={marker_radius:.1f}pt"
        f" | font={font_size}pt | box_w={box_width}pt | max_box_w={max_box_width}pt | gap={gap}pt"
    )

    # ── Estimate box height from line-wrapped text ────────────────────────────
    chars_per_line = max(1, int(box_width / CHAR_W))
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) <= chars_per_line:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    n_lines = max(1, len(lines))

    padding = 5.0
    line_height = font_size * 1.35
    box_height = n_lines * line_height + padding * 2
    box_height = max(box_height, font_size + padding * 2)

    # Minimum distance from marker centre to the nearest box edge
    min_dist = marker_radius + gap

    # ── Sizing diagnostics (derived) ──────────────────────────────────────────
    logger.info(
        f"   [sizing-out] chars_per_line={chars_per_line} | n_lines={n_lines}"
        f" | box={box_width:.0f}x{box_height:.1f}pt"
        f" | min_dist={min_dist:.1f}pt (radius {marker_radius:.1f} + gap {gap})"
        f" | page_fraction: box_w={box_width/page_rect.width*100:.1f}%"
        f"  radius={marker_radius/page_rect.width*100:.2f}%"
    )

    # ── 24 candidate directions (PDF coords: +y = down) ───────────────────────
    import math
    # Use exact direction tuples for cardinal/ordinal, computed for intermediates
    DIRS = []
    for a in range(0, 360, 15):
        rad = math.radians(a)
        dx = round(math.cos(rad), 6)
        dy = round(math.sin(rad), 6)
        # Snap near-zero values to exactly 0 so cardinal placement works
        if abs(dx) < 0.01:
            dx = 0.0
        if abs(dy) < 0.01:
            dy = 0.0
        DIRS.append((dx, dy))

    best_rect: fitz.Rect = None
    best_score = float("inf")  # lower = better; 0 = perfect

    # Gap between neighbouring callout boxes (enough to read clearly)
    MARGIN = font_size * 2.0

    # Distance steps: reach far across the page so boxes spread to open space.
    # Dense at short range, progressively sparser at long range.
    page_diag = (page_rect.width ** 2 + page_rect.height ** 2) ** 0.5
    DIST_MULTS = (
        1.0, 1.3, 1.7, 2.2, 3.0, 4.0, 5.5, 7.5, 10.0, 14.0,
        19.0, 26.0, 35.0, 48.0, 65.0, 90.0,
    )
    DIST_STEPS = [min_dist * m for m in DIST_MULTS]
    # Cap so no step exceeds 50% of page diagonal (allows reaching far corners)
    DIST_STEPS = [min(d, page_diag * 0.50) for d in DIST_STEPS]
    # Deduplicate after capping
    seen = set()
    DIST_STEPS = [d for d in DIST_STEPS if not (round(d, 1) in seen or seen.add(round(d, 1)))]

    # ── PASS 1: find a CLEAN placement (no overlaps, no crossings) ────────────
    # All violations are hard-reject.  Search ALL distances — never break early.
    # Score balances short leader lines with clearance from existing boxes.
    for effective_dist in DIST_STEPS:
        for dx, dy in DIRS:
            if dx > 0:
                bx0 = marker_x + effective_dist
            elif dx < 0:
                bx0 = marker_x - effective_dist - box_width
            else:
                bx0 = marker_x - box_width / 2

            if dy > 0:
                by0 = marker_y + effective_dist
            elif dy < 0:
                by0 = marker_y - effective_dist - box_height
            else:
                by0 = marker_y - box_height / 2

            candidate = fitz.Rect(bx0, by0, bx0 + box_width, by0 + box_height)

            # Must fit on page
            if not page_rect.contains(candidate):
                continue

            # Hard: no polygon fill overlap
            if forbidden_rects:
                if any(not (candidate & fr).is_empty for fr in forbidden_rects):
                    continue

            # Hard: no overlap with placed boxes (including margin)
            box_ok = True
            for placed in placed_boxes:
                padded = placed + (-MARGIN, -MARGIN, MARGIN, MARGIN)
                if not (candidate & padded).is_empty:
                    box_ok = False
                    break
            if not box_ok:
                continue

            # Hard: no overlap with marker safe zones
            if marker_zones:
                if any(not (candidate & mz).is_empty for mz in marker_zones):
                    continue

            # Compute proposed leader line
            ccx0, ccy0, ccx1, ccy1 = candidate.x0, candidate.y0, candidate.x1, candidate.y1
            cax = ccx0 if marker_x <= ccx0 else (ccx1 if marker_x >= ccx1 else (ccx0 + ccx1) / 2)
            cay = ccy0 if marker_y <= ccy0 else (ccy1 if marker_y >= ccy1 else (ccy0 + ccy1) / 2)
            c_attach = fitz.Point(cax, cay)
            c_tip = (_closest_point_on_polygon(c_attach, polygon_points)
                     if polygon_points else fitz.Point(marker_x, marker_y))

            if committed_lines:
                # Hard: leader line must not cross another leader line
                if any(_segments_intersect(c_attach, c_tip, cl_a, cl_t)
                       for cl_a, cl_t in committed_lines):
                    continue

                # Hard: leader line must not pass through a placed box
                if any(_segment_intersects_rect(c_attach, c_tip, pb)
                       for pb in placed_boxes):
                    continue

            # Hard: existing lines must not pass through this box
            if committed_lines:
                if any(_segment_intersects_rect(cl_a, cl_t, candidate)
                       for cl_a, cl_t in committed_lines):
                    continue

            # ── Score: balance short leader line vs clearance from neighbours ──
            # Clearance = distance to the nearest placed box edge.  A position
            # that is slightly further from the marker but surrounded by open
            # space is preferred over one that is close but squeezed between
            # existing boxes.
            min_clearance = page_diag
            for placed in placed_boxes:
                dx_gap = max(0, placed.x0 - candidate.x1, candidate.x0 - placed.x1)
                dy_gap = max(0, placed.y0 - candidate.y1, candidate.y0 - placed.y1)
                gap_dist = (dx_gap ** 2 + dy_gap ** 2) ** 0.5
                min_clearance = min(min_clearance, gap_dist)

            # Score: leader line length, penalised when squeezed near boxes.
            # Clearance reward caps at 3× box height so distant positions don't
            # win just because they're far from everything.
            clearance_cap = box_height * 3.0
            clearance_reward = min(min_clearance, clearance_cap) / clearance_cap  # 0..1
            score = effective_dist - clearance_reward * effective_dist * 0.4

            if score < best_score:
                best_score = score
                best_rect = candidate

    # ── PASS 2 (soft fallback): if no perfectly clean spot exists, allow
    # overlaps/crossings but penalise them heavily so we pick the least-bad option.
    if best_rect is None:
        logger.warning(f"   ⚠️  No clean placement found for '{text[:30]}…' — using soft fallback")
        BIG_PENALTY = page_diag * 1000
        best_score = float("inf")
        for effective_dist in DIST_STEPS:
            for dx, dy in DIRS:
                if dx > 0:
                    bx0 = marker_x + effective_dist
                elif dx < 0:
                    bx0 = marker_x - effective_dist - box_width
                else:
                    bx0 = marker_x - box_width / 2
                if dy > 0:
                    by0 = marker_y + effective_dist
                elif dy < 0:
                    by0 = marker_y - effective_dist - box_height
                else:
                    by0 = marker_y - box_height / 2

                candidate = fitz.Rect(bx0, by0, bx0 + box_width, by0 + box_height)
                if not page_rect.contains(candidate):
                    continue

                # Hard even in Pass 2: NEVER place on polygon fills
                if forbidden_rects:
                    if any(not (candidate & fr).is_empty for fr in forbidden_rects):
                        continue

                # Soft in Pass 2: heavily penalise overlap with markers/shapes
                # but don't hard-reject (box is rendered on top, still visible)
                marker_overlap_penalty = 0.0
                if marker_zones:
                    for mz in marker_zones:
                        inter = candidate & mz
                        if not inter.is_empty:
                            marker_overlap_penalty += inter.width * inter.height * 10

                score = effective_dist + marker_overlap_penalty

                for placed in placed_boxes:
                    padded = placed + (-MARGIN, -MARGIN, MARGIN, MARGIN)
                    inter = candidate & padded
                    if not inter.is_empty:
                        score += inter.width * inter.height

                ccx0, ccy0, ccx1, ccy1 = candidate.x0, candidate.y0, candidate.x1, candidate.y1
                cax = ccx0 if marker_x <= ccx0 else (ccx1 if marker_x >= ccx1 else (ccx0 + ccx1) / 2)
                cay = ccy0 if marker_y <= ccy0 else (ccy1 if marker_y >= ccy1 else (ccy0 + ccy1) / 2)
                c_attach = fitz.Point(cax, cay)
                c_tip = (_closest_point_on_polygon(c_attach, polygon_points)
                         if polygon_points else fitz.Point(marker_x, marker_y))

                if committed_lines:
                    for cl_a, cl_t in committed_lines:
                        if _segments_intersect(c_attach, c_tip, cl_a, cl_t):
                            score += BIG_PENALTY
                    for pb in placed_boxes:
                        if _segment_intersects_rect(c_attach, c_tip, pb):
                            score += BIG_PENALTY
                if committed_lines:
                    for cl_a, cl_t in committed_lines:
                        if _segment_intersects_rect(cl_a, cl_t, candidate):
                            score += BIG_PENALTY

                if score < best_score:
                    best_score = score
                    best_rect = candidate

    if best_rect is None:
        # All directions at all distances clipped by page bounds — clamp to right edge
        bx0 = min(marker_x + min_dist, page_rect.x1 - box_width)
        by0 = max(page_rect.y0, min(marker_y - box_height / 2, page_rect.y1 - box_height))
        best_rect = fitz.Rect(bx0, by0, bx0 + box_width, by0 + box_height)

    # ── Compute the callout leader-line attachment point ─────────────────────
    # Choose the point on the box border that is geometrically closest to the
    # marker centre.  This avoids the line piercing through the box itself.
    cx0, cy0, cx1, cy1 = best_rect.x0, best_rect.y0, best_rect.x1, best_rect.y1

    if marker_x <= cx0:
        ax = cx0
    elif marker_x >= cx1:
        ax = cx1
    else:
        ax = (cx0 + cx1) / 2  # same column → horizontal centre looks cleanest

    if marker_y <= cy0:
        ay = cy0
    elif marker_y >= cy1:
        ay = cy1
    else:
        ay = (cy0 + cy1) / 2  # same row → vertical centre

    attach = fitz.Point(ax, ay)

    # For polygons: snap to the perimeter then nudge the tip a few points into
    # the interior so the line visually pierces the fill edge rather than just
    # grazing it.  The nudge vector points from the perimeter point toward the
    # polygon centroid; clamped so it never overshoots the centroid.
    # For markers: use the marker centre as before.
    if polygon_points:
        perim_pt = _closest_point_on_polygon(attach, polygon_points)
        NUDGE = 15.0  # pt — how far inside the polygon the tip lands
        cx_poly = marker_x  # marker_x/y hold the centroid for polygons
        cy_poly = marker_y
        vx, vy = cx_poly - perim_pt.x, cy_poly - perim_pt.y
        vlen = (vx * vx + vy * vy) ** 0.5
        if vlen > 0:
            nudge = min(NUDGE, vlen)  # don't overshoot centroid
            tip = fitz.Point(perim_pt.x + vx / vlen * nudge,
                             perim_pt.y + vy / vlen * nudge)
        else:
            tip = perim_pt
    else:
        tip = fitz.Point(marker_x, marker_y)

    # ── Add the FreeText box (NO embedded callout) ───────────────────────────
    # The leader line is drawn AFTER all boxes are placed, as a separate
    # add_line_annot() call.  This guarantees lines render on top of every
    # box fill in the resulting PDF / pixmap (annotations render in /Annots
    # order, so later annotations paint over earlier ones).
    annot = page.add_freetext_annot(
        best_rect,
        text,
        fontsize=font_size,
        fontname="hebo",
        fill_color=(1, 1, 0.667),       # light yellow box background
        text_color=(0, 0, 0),            # black text + border
        border_width=1.5,
    )

    placed_boxes.append(best_rect)
    logger.info(f"✅ Callout placed at {best_rect} → tip ({marker_x:.1f}, {marker_y:.1f}), overlap={best_score:.0f}")

    # Return the leader-line endpoints so the caller can draw them as Line
    # annotations AFTER all FreeText annotations are placed.
    return (attach, tip)


# ──────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC RETIRED — findings summary:
#   text_color = controls text color, box border stroke AND arrow line (all one color)
#   fill_color = controls box background fill
#   border_color / set_colors() = raise ValueError for FreeText in this build
#   xref_set_key("C") + update() = changes BOX FILL to /C value (not line color)
# Production fix: text_color=(1,1,0) [yellow] in constructor gives black box +
#   yellow text + yellow arrow + yellow border. No post-update needed.
# ──────────────────────────────────────────────────────────────────────────────
# DIAGNOSTIC: 15-variant FreeText callout grid (retired – kept for reference)
# Renders once per export in the top-left corner to identify which API
# combination actually produces a coloured callout border/line.
#
# Layout:  3 columns × 5 rows  (origin 10, 10)
#   Box:   120 × 45 pt
#   Tip:   35 pt right + 13 pt below box right-centre  (angled arrow)
#   Cell:  170 × 65 pt  →  total footprint ≈ 510 × 325 pt
#
# Variant index (V01–V15) → configuration:
#   Row 1 – baseline + update(text_color) ordering
#     V01  baseline: fill=black, text=white, no mutation
#     V02  update(text_color=Y) then bare update()
#     V03  bare update() first, then update(text_color=Y)
#   Row 2 – update() fill_color and text_color
#     V04  update(text_color=Y)
#     V05  update(fill_color=Y)  [yellow box]
#     V06  update(text_color=Y) + update(fill_color=Y)
#   Row 3 – xref /C only (no update — does AP rebuild happen automatically?)
#     V07  xref C=yellow, no update()
#     V08  xref C=red,    no update()
#     V09  xref C=green,  no update()
#   Row 4 – xref /C + update() (forces AP stream rebuild)
#     V10  xref C=yellow + update()
#     V11  xref C=red    + update()
#     V12  xref C=green  + update()
#   Row 5 – xref /C + update() combined
#     V13  xref C=yellow + update(fill_color=black)
#     V14  xref C=yellow + xref IC=black + update()
#     V15  ctor fill=blue + xref C=yellow + update()
# ──────────────────────────────────────────────────────────────────────────────
def _diag_callout_variants_RETIRED(page: fitz.Page) -> None:
    """Render 15 FreeText callout annotation variants at top-left of page."""
    BOX_W, BOX_H = 120, 45
    COLS = 3
    H_CELL = 170   # 120 box + 35 arrow + 15 gap
    V_CELL = 65    # 45 box + 20 row-gap
    OX, OY = 10, 10

    doc = page.parent

    # (id, description, ctor_extra_kwargs, post_actions)
    # post_actions are string tokens processed in order below.
    # NOTE: border_color raises ValueError (rich_text=False) in BOTH ctor and
    #       update() — it is completely unavailable without rich_text mode.
    VARIANTS = [
        # Row 1 – baseline + update(text_color) ordering
        ("V01", "baseline\n(no mutation)",            {},                       []),
        ("V02", "upd(tc=Y)\nthen update()",           {},                       ["upd_tc_Y", "update"]),
        ("V03", "update()\nthen upd(tc=Y)",           {},                       ["update", "upd_tc_Y"]),
        # Row 2 – update() fill_color and text_color
        ("V04", "update(\ntext_color=Y)",             {},                       ["upd_tc_Y"]),
        ("V05", "update(\nfill_color=Y)",             {},                       ["upd_fill_Y"]),
        ("V06", "upd(tc=Y)\n+ upd(fill=Y)",          {},                       ["upd_tc_Y", "upd_fill_Y"]),
        # Row 3 – xref /C only (no update)
        ("V07", "xref C=Y\nno update",                {},                       ["xref_C_Y"]),
        ("V08", "xref C=R\nno update",                {},                       ["xref_C_R"]),
        ("V09", "xref C=G\nno update",                {},                       ["xref_C_G"]),
        # Row 4 – xref /C + update()
        ("V10", "xref C=Y\n+ update()",               {},                       ["xref_C_Y", "update"]),
        ("V11", "xref C=R\n+ update()",               {},                       ["xref_C_R", "update"]),
        ("V12", "xref C=G\n+ update()",               {},                       ["xref_C_G", "update"]),
        # Row 5 – xref /C + update() variants
        ("V13", "xref C=Y\n+upd(fill=K)",             {},                       ["xref_C_Y", "upd_fill_K"]),
        ("V14", "xref C=Y\n+xref IC=K+upd",          {},                       ["xref_C_Y", "xref_IC_K", "update"]),
        ("V15", "fill=BLUE\nxref C=Y+upd",           {"fill_color": (0, 0, 1)}, ["xref_C_Y", "update"]),
    ]

    shape = page.new_shape()
    for idx, (vid, desc, ctor_extra, post_actions) in enumerate(VARIANTS):
        col = idx % COLS
        row = idx // COLS
        x0 = OX + col * H_CELL
        y0 = OY + row * V_CELL
        rect = fitz.Rect(x0, y0, x0 + BOX_W, y0 + BOX_H)
        attach = fitz.Point(x0 + BOX_W, y0 + BOX_H / 2)
        tip    = fitz.Point(x0 + BOX_W + 35, y0 + BOX_H / 2 + 13)

        # Build constructor kwargs – defaults then variant overrides
        ctor_kw: dict = {
            "fontsize":    7,
            "fontname":    "helv",
            "fill_color":  (0, 0, 0),   # default: black box
            "text_color":  (1, 1, 1),   # default: white text
            "border_width": 1.5,
            "callout":     [tip, attach],
            "line_end":    fitz.PDF_ANNOT_LE_OPEN_ARROW,
        }
        # Apply variant ctor overrides (these may replace fill_color / text_color)
        ctor_kw.update(ctor_extra)

        label = f"{vid}\n{desc}"
        annot = page.add_freetext_annot(rect, label, **ctor_kw)

        # Post-creation mutations
        for action in post_actions:
            if action == "update":
                annot.update()
            elif action == "upd_fill_K":
                annot.update(fill_color=(0, 0, 0))
            elif action == "upd_fill_Y":
                annot.update(fill_color=(1, 1, 0))
            elif action == "upd_tc_Y":
                annot.update(text_color=(1, 1, 0))
            elif action == "xref_C_Y":
                doc.xref_set_key(annot.xref, "C", "[1 1 0]")
            elif action == "xref_C_R":
                doc.xref_set_key(annot.xref, "C", "[1 0 0]")
            elif action == "xref_C_G":
                doc.xref_set_key(annot.xref, "C", "[0 1 0]")
            elif action == "xref_IC_K":
                doc.xref_set_key(annot.xref, "IC", "[0 0 0]")

        # Small dot at the tip so we can see the target even if arrow is invisible
        shape.draw_circle(tip, 3)
        shape.finish(color=(0, 0, 0), fill=(1, 1, 0), width=0.5)

    shape.commit()
    logger.info(f"🧪 DIAG: rendered {len(VARIANTS)} callout variants at top-left")


async def download_file(url: str) -> bytes:
    """
    Download a file from a URL.

    Args:
        url: File URL to download

    Returns:
        File content as bytes
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def annotate_pdf(pdf_bytes: bytes, objects: List[Dict[str, Any]],
                metadata: Dict[str, Any]) -> bytes:
    """
    Annotate a PDF with shapes and markers.

    Args:
        pdf_bytes: Original PDF content
        objects: List of GeoJSON feature objects to draw
        metadata: Metadata containing coordinate system info

    Returns:
        Annotated PDF as bytes (returns original bytes unmodified on failure)
    """
    # ── PDF header / size validation ─────────────────────────────────────────
    logger.info(f"PDF bytes received: {len(pdf_bytes):,} bytes")
    if not pdf_bytes:
        logger.error("PDF bytes are empty. Returning original.")
        return pdf_bytes
    magic = pdf_bytes[:8]
    logger.info(f"PDF magic bytes: {magic!r}")
    if magic[:5] != b"%PDF-":
        logger.error(f"Downloaded content is NOT a PDF ({len(pdf_bytes):,} bytes, magic={pdf_bytes[:20]!r}). Returning original.")
        return pdf_bytes
    # Log PDF version string (e.g. b'%PDF-1.7')
    version_line = pdf_bytes[:20].split(b"\n")[0].strip()
    logger.info(f"PDF version header: {version_line!r}")

    # ── Open PDF ──────────────────────────────────────────────────────────────
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as open_err:
        logger.error(f"fitz.open() raised an exception: {open_err!r} — PDF may be corrupt. Returning original.", exc_info=True)
        return pdf_bytes

    logger.info(f"fitz.open() succeeded")
    logger.info(f"  is_pdf       : {doc.is_pdf}")
    logger.info(f"  page_count   : {doc.page_count}")
    logger.info(f"  needs_pass   : {doc.needs_pass}")
    logger.info(f"  is_encrypted : {doc.is_encrypted}")
    logger.info(f"  is_repaired  : {doc.is_repaired}")
    try:
        pdf_meta = doc.metadata
        logger.info(
            f"  metadata     : producer={pdf_meta.get('producer')!r}  "
            f"creator={pdf_meta.get('creator')!r}  "
            f"format={pdf_meta.get('format')!r}"
        )
    except Exception:
        logger.warning("  metadata     : (could not read)")

    if not doc.is_pdf or doc.page_count == 0:
        logger.error(f"fitz opened file but is_pdf={doc.is_pdf}, pages={doc.page_count}. Returning original.")
        doc.close()
        return pdf_bytes

    page = doc[0]  # First page
    logger.info(f"Page 0 info:")
    logger.info(f"  mediabox     : {page.mediabox}")
    logger.info(f"  cropbox      : {page.cropbox}")
    logger.info(f"  rect         : {page.rect}  ({page.rect.width:.1f} x {page.rect.height:.1f} pt)")
    logger.info(f"  rotation     : {page.rotation}°")
    existing_annots = list(page.annots())
    logger.info(f"  existing annots: {len(existing_annots)} " +
                 ("(" + ", ".join(a.type[1] for a in existing_annots) + ")" if existing_annots else "(none)"))

    logger.info(f"=" * 80)
    logger.info(f"PDF ANNOTATION")
    logger.info(f"=" * 80)

    # ── Floorplan specs ───────────────────────────────────────────────────────
    pdf_w = page.rect.width
    pdf_h = page.rect.height
    img_w = metadata['source_image']['width']
    img_h = metadata['source_image']['height']
    pts_per_mm = 2.8346
    px_per_pt_x = img_w / pdf_w
    px_per_pt_y = img_h / pdf_h

    logger.info(f"  PDF size   : {pdf_w:.1f} x {pdf_h:.1f} pt  ({pdf_w/pts_per_mm:.1f} x {pdf_h/pts_per_mm:.1f} mm)")
    logger.info(f"  Image size : {img_w} x {img_h} px")
    logger.info(f"  Px/pt ratio: {px_per_pt_x:.3f} x (horiz)  {px_per_pt_y:.3f} y (vert)")
    logger.info(f"  1 pt = {1/px_per_pt_x:.2f} px (horiz)  |  1 px = {px_per_pt_x:.3f} pt")
    logger.info(f"  Default callout: font=9pt ({9/pts_per_mm:.1f}mm)  box=130x? pt ({130/pts_per_mm:.1f}mm wide)")

    # ── Dynamic callout sizing from page dimensions + annotation density ──────
    # Font should be small & fixed-ish — annotations are read at arm's length
    # regardless of paper size.  Use a gentle log scale, not linear.
    import math as _math
    A4_AREA = 595.0 * 842.0  # A4 reference area in pt²
    page_scale = _math.sqrt(pdf_w * pdf_h / A4_AREA)  # 1.0 for A4, ~1.41 A3, ~4.0 A0

    # Step 2: count how many callouts we'll place to adjust for density
    n_callouts = sum(
        1 for obj in objects
        if obj.get("overlay") or obj.get("properties", {}).get("overlay")
        or obj.get("properties", {}).get("content") or obj.get("properties", {}).get("label")
    )
    n_callouts = max(n_callouts, 1)

    # Font: ~13.5pt on A4, ~15pt on A3, ~19pt on A1, ~21pt on A0
    callout_font_size = round(min(26.0, (9.0 + 3.0 * _math.log2(max(1.0, page_scale))) * 1.8), 1)

    # Box width cap: 18% of page width
    callout_max_box_width = round(pdf_w * 0.18)

    logger.info(f"  Dynamic callout: font={callout_font_size}pt"
                 f"  page_scale={page_scale:.2f}  n_callouts={n_callouts}"
                 f"  max_box_w={callout_max_box_width}pt ({callout_max_box_width/pdf_w*100:.0f}%)")

    # Count object types
    type_counts: Dict[str, int] = {}
    for obj in objects:
        geo_type = obj.get("geometry", {}).get("type", "unknown")
        type_counts[geo_type] = type_counts.get(geo_type, 0) + 1
    logger.info(f"  Objects    : {len(objects)} total — " + ", ".join(f"{v}x {k}" for k, v in type_counts.items()))
    logger.info(f"=" * 80)

    # ── Dump all incoming objects for debugging ───────────────────────────────
    logger.info("INCOMING OBJECTS DUMP:")
    for _di, _obj in enumerate(objects):
        _props = _obj.get("properties", {})
        _geom  = _obj.get("geometry", {})
        logger.info(
            f"  [{_di+1}/{len(objects)}] geo={_geom.get('type')} "
            f"prop_type={_props.get('type')} "
            f"overlay={_props.get('overlay') or _obj.get('overlay')!r} "
            f"label={_props.get('label')!r} "
            f"content={_props.get('content')!r} "
            f"text={_props.get('text')!r} "
            f"color={_props.get('color')!r} "
            f"fontSize={_props.get('fontSize')!r} "
            f"coords={str(_geom.get('coordinates', []))[:80]}"
        )
    logger.info(f"=" * 80)

    # Detect whitespace trim offset (needed when PDF had margins that were cropped)
    trim_offset = detect_trim_offset(page, metadata)
    logger.info(f"Trim offset: left={trim_offset[0]:.1f}, top={trim_offset[1]:.1f} px")
    logger.info(f"=" * 80)

    # Process each object
    # pending_callouts collects (x_pdf, y_pdf, radius, text) for markers with
    # overlays.  Callout annotations are placed *after* all shapes are burned in
    # so the layout algorithm can avoid them properly.
    pending_callouts: List[Tuple[float, float, float, str]] = []
    shape_rects: List[fitz.Rect] = []   # bounding rects of all burned shapes
    polygon_rects: List[fitz.Rect] = [] # hard-exclusion zones (polygon fills)
    marker_zones: List[fitz.Rect] = []  # safe zones around each marker (boxes must not cover)
    objects_drawn = 0
    for i, obj in enumerate(objects):
        try:
            logger.info(f"\n--- Object {i + 1}/{len(objects)} ---")
            properties = obj.get("properties", {})
            obj_type = properties.get("type", "unknown")
            geometry = obj.get("geometry", {})
            geo_type = geometry.get("type")
            coordinates = geometry.get("coordinates", [])

            logger.info(f"Type: {obj_type}, Geometry: {geo_type}, Properties: {properties}")

            if geo_type == "Polygon":
                config = ANNOTATION_CONFIG["polygon"].copy()
                overlay = obj.get("overlay") or properties.get("overlay")
                logger.info(f"   config: fill_opacity={config['fill_opacity']}, stroke_width={config['stroke_width']}, points={len(coordinates[0]) if coordinates else 0}, overlay={overlay!r}")
                draw_polygon_on_pdf(page, coordinates, metadata, config, overlay, trim_offset, pending_callouts, shape_rects, polygon_rects)
                objects_drawn += 1

            elif geo_type == "Point" and obj_type == "text":
                # Text field: render as a FreeText callout/label at position
                text_content = (properties.get("text") or properties.get("content")
                                or properties.get("label") or properties.get("overlay") or "")
                logger.info(f"   TEXT FIELD: content={text_content!r}, coords={coordinates}")
                if text_content:
                    x_pdf, y_pdf = transform_coords(coordinates, metadata, trim_offset)
                    logger.info(f"   TEXT FIELD -> PDF coords: ({x_pdf:.2f}, {y_pdf:.2f})")
                    text_config = ANNOTATION_CONFIG["text"].copy()
                    font_size_override = properties.get("fontSize")
                    if font_size_override:
                        try:
                            text_config["font_size"] = float(font_size_override)
                        except (TypeError, ValueError):
                            pass
                    draw_text_on_pdf(page, [x_pdf, y_pdf], text_content, text_config)
                    logger.info(f"✅ Text field drawn: {text_content!r} at PDF ({x_pdf:.1f}, {y_pdf:.1f})")
                    objects_drawn += 1
                else:
                    logger.warning(f"⚠️  Text field has no content — properties={properties}")

            elif geo_type == "Point":
                config = ANNOTATION_CONFIG["marker"].copy()
                label = properties.get("content") or properties.get("label")
                overlay = obj.get("overlay") or properties.get("overlay")
                logger.info(f"   MARKER: label={label!r}, overlay={overlay!r}, coords={coordinates}")
                draw_marker_on_pdf(page, coordinates, metadata, config, label, overlay, trim_offset, pending_callouts, shape_rects)
                objects_drawn += 1

            else:
                logger.warning(
                    f"⚠️  Unhandled object: geo_type={geo_type!r}, obj_type={obj_type!r}, "
                    f"properties={properties}, coords={str(coordinates)[:80]}"
                )

        except Exception as e:
            logger.error(f"❌ Error drawing object {i + 1}: {str(e)}", exc_info=True)
            continue

    # ── Place deferred Callout annotations ──────────────────────────────────
    # Done after all burned-in shapes so the placement algorithm sees a clean
    # page with no shape outlines interfering with the overlap check.
    leader_lines: List[Tuple[fitz.Point, fitz.Point]] = []  # (attach, tip) pairs to render as Line annots
    if pending_callouts:
        # ── Cluster marker callouts (4-tuple) with IDENTICAL text ─────────
        # Polygon callouts (5-tuple) stay individual — they need perimeter
        # snapping which only makes sense per-polygon.
        polygon_callouts: List = []
        clusters: List[Tuple[List[Tuple[float, float, float]], str]] = []
        text_to_cluster: Dict[str, int] = {}
        for item in pending_callouts:
            if len(item) > 4:
                polygon_callouts.append(item)
                continue
            mx, my, mr, txt = item
            if txt in text_to_cluster:
                clusters[text_to_cluster[txt]][0].append((mx, my, mr))
            else:
                text_to_cluster[txt] = len(clusters)
                clusters.append(([(mx, my, mr)], txt))

        n_marker_callouts = sum(len(c[0]) for c in clusters)
        logger.info(
            f"\nCallout clustering: {n_marker_callouts} marker callout(s) → "
            f"{len(clusters)} unique-text group(s); {len(polygon_callouts)} polygon callout(s)"
        )
        for ci, (markers, txt) in enumerate(clusters):
            if len(markers) > 1:
                logger.info(f"  cluster {ci+1}: {len(markers)}× '{txt[:50]}'")

        # Build marker safe zones from ALL drawn shapes (markers + polygons)
        # so text boxes never cover any drawn annotation on the floorplan.
        SAFE_PAD = 20.0  # generous clearance around every shape
        for sr in shape_rects:
            padded = sr + (-SAFE_PAD, -SAFE_PAD, SAFE_PAD, SAFE_PAD)
            marker_zones.append(padded)
        # Also add extra-padded zones around each marker anchor point
        for markers, _ in clusters:
            for mx, my, mr in markers:
                pad = mr + SAFE_PAD
                marker_zones.append(fitz.Rect(mx - pad, my - pad, mx + pad, my + pad))
        for item in polygon_callouts:
            mx, my, mr = item[0], item[1], item[2]
            pad = mr + SAFE_PAD
            marker_zones.append(fitz.Rect(mx - pad, my - pad, mx + pad, my + pad))

        # Seed with shape bounding boxes so callouts won't overlap fills/circles.
        placed_boxes: List[fitz.Rect] = list(shape_rects)
        committed_lines: List[Tuple[fitz.Point, fitz.Point]] = []

        # ── Place clustered marker callouts ────────────────────────────────
        for markers, txt in clusters:
            # Compute centroid of all markers in the cluster
            cx = sum(m[0] for m in markers) / len(markers)
            cy = sum(m[1] for m in markers) / len(markers)
            # Effective radius: max distance from centroid to any marker + that
            # marker's own radius.  Guarantees the box clears every marker.
            eff_radius = max(
                ((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5 + mr
                for mx, my, mr in markers
            )
            try:
                result = place_callout_annotation(
                    page, cx, cy, eff_radius, txt, placed_boxes,
                    font_size=callout_font_size,
                    max_box_width=callout_max_box_width,
                    polygon_points=None,
                    forbidden_rects=polygon_rects,
                    committed_lines=committed_lines,
                    marker_zones=marker_zones,
                )
            except Exception as e:
                logger.error(f"❌ Failed to place callout '{txt}': {e}", exc_info=True)
                continue

            if not result:
                continue

            # The placed box is the last one appended to placed_boxes.
            box_rect = placed_boxes[-1]

            # For each marker in the cluster, draw a leader line from the
            # closest point on the box border to the marker centre.
            for mx, my, mr in markers:
                bx0, by0, bx1, by1 = box_rect.x0, box_rect.y0, box_rect.x1, box_rect.y1
                ax = bx0 if mx <= bx0 else (bx1 if mx >= bx1 else (bx0 + bx1) / 2)
                ay = by0 if my <= by0 else (by1 if my >= by1 else (by0 + by1) / 2)
                attach_pt = fitz.Point(ax, ay)
                tip_pt = fitz.Point(mx, my)
                leader_lines.append((attach_pt, tip_pt))
                committed_lines.append((attach_pt, tip_pt))

        # ── Place polygon callouts (unchanged, perimeter-snap behaviour) ──
        for item in polygon_callouts:
            cx, cy, r, callout_text = item[:4]
            poly_pts = item[4]
            try:
                result = place_callout_annotation(
                    page, cx, cy, r, callout_text, placed_boxes,
                    font_size=callout_font_size,
                    max_box_width=callout_max_box_width,
                    polygon_points=poly_pts,
                    forbidden_rects=polygon_rects,
                    committed_lines=committed_lines,
                    marker_zones=marker_zones,
                )
                if result:
                    leader_lines.append(result)
                    committed_lines.append(result)
            except Exception as e:
                logger.error(f"❌ Failed to place callout '{callout_text}': {e}", exc_info=True)

    # ── Draw leader lines as Line annotations (rendered ON TOP of all boxes) ─
    if leader_lines:
        logger.info(f"Drawing {len(leader_lines)} leader line annotation(s)...")
        for attach_pt, tip_pt in leader_lines:
            try:
                line_annot = page.add_line_annot(attach_pt, tip_pt)
                line_annot.set_colors(stroke=(0, 0, 0))
                line_annot.set_border(width=1.5)
                line_annot.update()
            except Exception as e:
                logger.error(f"❌ Failed to draw leader line: {e}", exc_info=True)
        logger.info(f"✅ {len(leader_lines)} leader line(s) drawn on top of callout boxes")

    logger.info(f"\n{'=' * 80}")
    logger.info(f"COMPLETE: {objects_drawn}/{len(objects)} objects drawn, {len(pending_callouts)} callout(s) placed")
    logger.info(f"{'=' * 80}\n")

    # ── Save annotated PDF ────────────────────────────────────────────────────
    logger.info("Saving annotated PDF...")
    logger.info(f"  Input size      : {len(pdf_bytes):,} bytes")
    output = io.BytesIO()

    # Incremental save first (safe — only appends, never touches broken xrefs)
    incremental_bytes = None
    try:
        incremental_bytes = doc.tobytes(incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        logger.info(f"✅ Incremental save succeeded: {len(incremental_bytes):,} bytes "
                     f"(+{len(incremental_bytes)-len(pdf_bytes):+,} bytes vs input)")
    except Exception as inc_err:
        logger.warning(f"⚠️  Incremental save failed: {inc_err!r}")

    # Try clean save (smaller output, removes orphans)
    try:
        doc.save(output, garbage=3, deflate=True)
        clean_bytes = output.getvalue()
        doc.close()
        logger.info(f"✅ Clean save succeeded: {len(clean_bytes):,} bytes "
                     f"(+{len(clean_bytes)-len(pdf_bytes):+,} bytes vs input)")
        return clean_bytes
    except Exception as save_err:
        logger.warning(f"⚠️  Clean save failed: {save_err!r}")

    doc.close()

    if incremental_bytes:
        logger.info("Using incremental save as fallback.")
        return incremental_bytes

    logger.error("⚠️  Both save methods failed, returning original PDF unmodified")
    return pdf_bytes


# ==========================================
# PDF ANNOTATION ENDPOINT
# ==========================================

def register_routes(app: func.FunctionApp):
    """
    Register PDF annotation routes with the function app.

    Args:
        app: Azure Function App instance
    """

    @app.route(route="pdf-annotation", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
    async def pdf_annotation(req: func.HttpRequest) -> func.HttpResponse:
        """
        Annotate a PDF with shapes and markers from Leaflet drawings.

        Request body:
        {
            "file_url": "https://example.com/floorplan.pdf",
            "metadata_url": "https://example.com/floorplan/metadata.json",
            "objects": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [[[lat, lon], ...]]},
                    "properties": {"type": "rectangle"}
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lat, lon]},
                    "properties": {"type": "marker", "content": "Label"}
                }
            ]
        }

        Returns:
        {
            "success": true,
            "annotated_pdf_url": "https://...",
            "filename": "floorplan-annotation-[timestamp].pdf"
        }
        """
        try:
            # Parse request body
            try:
                body = req.get_json()
            except ValueError:
                return func.HttpResponse(
                    json.dumps({"success": False, "error": "Invalid JSON in request body"}),
                    status_code=400,
                    mimetype="application/json"
                )

            # Validate required fields
            file_url = body.get("file_url")
            metadata_url = body.get("metadata_url")
            objects = body.get("objects", [])

            if not file_url:
                return func.HttpResponse(
                    json.dumps({"success": False, "error": "file_url is required"}),
                    status_code=400,
                    mimetype="application/json"
                )

            if not metadata_url:
                return func.HttpResponse(
                    json.dumps({"success": False, "error": "metadata_url is required"}),
                    status_code=400,
                    mimetype="application/json"
                )

            # If file_url doesn't point to a PDF, derive the PDF path from metadata_url.
            # metadata_url pattern: .../floorplans/{file_id}/metadata.json
            # PDF pattern:          .../floorplans/{file_id}/{file_id}.pdf
            if not file_url.lower().endswith(".pdf"):
                base_dir = metadata_url.rsplit("/", 1)[0]  # strip "metadata.json"
                file_id = base_dir.rsplit("/", 1)[-1]       # last path segment = file_id
                derived_pdf_url = f"{base_dir}/{file_id}.pdf"
                logger.info(f"⚠️  file_url is not a PDF ({file_url}), deriving PDF URL: {derived_pdf_url}")
                file_url = derived_pdf_url

            logger.info(f"📝 Starting PDF annotation")
            logger.info(f"   PDF URL: {file_url}")
            logger.info(f"   Metadata URL: {metadata_url}")
            logger.info(f"   Objects to draw: {len(objects)}")

            # Download metadata
            logger.info("⬇️ Downloading metadata...")
            metadata_bytes = await download_file(metadata_url)
            metadata = json.loads(metadata_bytes.decode('utf-8'))
            logger.info(f"✅ Metadata loaded: {metadata.get('floorplan_id')}")

            # Download PDF
            logger.info("⬇️ Downloading PDF...")
            pdf_bytes = await download_file(file_url)
            logger.info(f"✅ PDF downloaded: {len(pdf_bytes)} bytes")

            # Annotate PDF
            logger.info("🎨 Annotating PDF...")
            annotated_pdf_bytes = annotate_pdf(pdf_bytes, objects, metadata)
            logger.info(f"✅ PDF annotated: {len(annotated_pdf_bytes)} bytes")

            # Generate filename with timestamp
            timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

            # Extract original filename without extension
            original_filename = file_url.split("/")[-1].rsplit(".", 1)[0]
            annotated_filename = f"{original_filename}-annotation-{timestamp}.pdf"

            # Upload to Azure Blob Storage
            connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
            if not connection_string:
                return func.HttpResponse(
                    json.dumps({"success": False, "error": "Azure Storage connection string not configured"}),
                    status_code=500,
                    mimetype="application/json"
                )

            logger.info("☁️ Uploading to Azure Blob Storage...")
            blob_service = BlobServiceClient.from_connection_string(connection_string)

            # Upload to 'annotated-pdfs' container
            container_name = "annotated-pdfs"
            try:
                container_client = blob_service.get_container_client(container_name)
                container_client.get_container_properties()
            except:
                # Create container if it doesn't exist
                container_client = blob_service.create_container(container_name, public_access="blob")
                logger.info(f"Created container: {container_name}")

            # Upload the annotated PDF
            blob_client = blob_service.get_blob_client(container_name, annotated_filename)
            blob_client.upload_blob(
                annotated_pdf_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="application/pdf")
            )

            # Generate the public URL
            annotated_pdf_url = f"https://blocksplayground.blob.core.windows.net/{container_name}/{annotated_filename}"

            logger.info(f"✅ Upload complete!")
            logger.info(f"   URL: {annotated_pdf_url}")

            # Return success response
            return func.HttpResponse(
                json.dumps({
                    "success": True,
                    "annotated_pdf_url": annotated_pdf_url,
                    "filename": annotated_filename,
                    "objects_drawn": len(objects),
                    "metadata": {
                        "floorplan_id": metadata.get("floorplan_id"),
                        "source_url": file_url
                    }
                }),
                status_code=200,
                mimetype="application/json"
            )

        except httpx.HTTPError as e:
            logger.error(f"❌ Download error: {str(e)}")
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Failed to download file: {str(e)}"
                }),
                status_code=400,
                mimetype="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Error annotating PDF: {str(e)}", exc_info=True)
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Error annotating PDF: {str(e)}",
                    "error_type": type(e).__name__
                }),
                status_code=500,
                mimetype="application/json"
            )
