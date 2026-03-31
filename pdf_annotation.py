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
        logging.info("No whitespace trimming detected — using direct formula")
        return (0.0, 0.0)

    logging.info(f"Whitespace trimming detected!")
    logging.info(f"  Pre-trim:  {pretrim_w:.0f} x {pretrim_h:.0f} px")
    logging.info(f"  Post-trim: {img_w} x {img_h} px")
    logging.info(f"  Trimmed:   {pretrim_w - img_w:.0f} x {pretrim_h - img_h:.0f} px")

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
        logging.warning("Could not detect content bbox — using (0, 0) offset")
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

    logging.info(f"  Content bbox at {detect_scale}x: left={bbox[0]}, top={bbox[1]}")
    logging.info(f"  Trim offset (at pdf_scale): left={trim_left:.1f}, top={trim_top:.1f} px")

    # Verify: post-trim dimensions should roughly match metadata
    right_detect = min(pix.width, bbox[2] + padding_at_detect)
    bottom_detect = min(pix.height, bbox[3] + padding_at_detect)
    detected_w = (right_detect - left_detect) * pdf_scale / detect_scale
    detected_h = (bottom_detect - top_detect) * pdf_scale / detect_scale
    logging.info(f"  Detected content size: {detected_w:.0f} x {detected_h:.0f} px (metadata: {img_w} x {img_h})")

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

    logging.info(f"Drawing polygon with {len(outer_ring)} points")

    # Convert coords to PDF coordinates
    pdf_points = []
    for point in outer_ring:
        x, y = point[0], point[1]
        logging.info(f"  Leaflet: [{x}, {y}]")
        x_pdf, y_pdf = transform_coords([x, y], metadata, trim_offset)
        logging.info(f"  -> PDF: [{x_pdf:.2f}, {y_pdf:.2f}]")
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
        logging.info(f"✅ Polygon drawn with {len(pdf_points)} points")

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
            logging.info(f"   Polygon overlay queued: centroid=({cx:.1f},{cy:.1f}), circumradius={circumradius:.1f}")
    else:
        logging.warning(f"⚠️  Not enough points: {len(pdf_points)}")


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
    logging.info(f"Drawing marker at [{x}, {y}]")

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
    logging.info(f"✅ Marker circle annotation placed at ({x_pdf:.1f}, {y_pdf:.1f})")
    if shape_rects is not None:
        shape_rects.append(circ_rect)

    # Both label and overlay become separate Callout annotations, each with
    # their own arrow pointing at the marker centre.
    if pending_callouts is not None:
        if label:
            pending_callouts.append((x_pdf, y_pdf, radius, label))
            logging.info(f"   Label queued for callout: '{label}'")
        if overlay:
            pending_callouts.append((x_pdf, y_pdf, radius, overlay))
            logging.info(f"   Overlay queued for callout: '{overlay}'")
    else:
        if label or overlay:
            logging.warning("   label/overlay present but no pending_callouts list provided — skipped")


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
        committed_lines: List[Tuple[fitz.Point, fitz.Point]] = None) -> None:
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
    logging.info(
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
    logging.info(
        f"   [sizing-out] chars_per_line={chars_per_line} | n_lines={n_lines}"
        f" | box={box_width:.0f}x{box_height:.1f}pt"
        f" | min_dist={min_dist:.1f}pt (radius {marker_radius:.1f} + gap {gap})"
        f" | page_fraction: box_w={box_width/page_rect.width*100:.1f}%"
        f"  radius={marker_radius/page_rect.width*100:.2f}%"
    )

    # ── 16 candidate directions (PDF coords: +y = down) ───────────────────────
    # 8 cardinal + 8 intermediate for finer placement in crowded layouts.
    import math
    DIRS = [(round(math.cos(math.radians(a)), 4), round(math.sin(math.radians(a)), 4))
            for a in range(0, 360, 22)]  # 0, 22, 45, 67, 90 … 338 → 16 dirs

    best_rect: fitz.Rect = None
    best_score = float("inf")  # lower overlap area = better

    # Each already-placed rect is expanded by this many points on every side
    # before the overlap check so callout boxes always have breathing room.
    MARGIN = 10.0

    # Try expanding distance multipliers — more steps to escape crowded areas.
    for dist_mult in (1.0, 1.4, 2.0, 2.8, 3.8, 5.0, 7.0):
        effective_dist = min_dist * dist_mult

        for dx, dy in DIRS:
            # Position the box so its nearest edge is exactly effective_dist from center
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

            # Discard candidates that fall outside the page
            if not page_rect.contains(candidate):
                continue

            # Hard exclusion: polygon fill areas must never be covered.
            # Any intersection (even tiny) gives infinite penalty so the
            # algorithm always prefers a position clear of polygon fills.
            if forbidden_rects:
                forbidden = False
                for frect in forbidden_rects:
                    if not (candidate & frect).is_empty:
                        forbidden = True
                        break
                if forbidden:
                    continue  # skip — try next direction / distance

            # Compute total overlap area against already-placed boxes + margin
            overlap = 0.0
            for placed in placed_boxes:
                padded = placed + (-MARGIN, -MARGIN, MARGIN, MARGIN)
                inter = candidate & padded
                if not inter.is_empty:
                    overlap += inter.width * inter.height

            # Crossing penalty: compute the proposed leader line for this
            # candidate and count how many committed lines it would cross.
            # One crossing costs more than a full box overlap so the optimiser
            # strongly prefers non-crossing placements without breaking ties
            # in impossible layouts.
            if committed_lines:
                # Attach point for this candidate (same logic as the final block)
                ccx0, ccy0, ccx1, ccy1 = candidate.x0, candidate.y0, candidate.x1, candidate.y1
                cax = ccx0 if marker_x <= ccx0 else (ccx1 if marker_x >= ccx1 else (ccx0 + ccx1) / 2)
                cay = ccy0 if marker_y <= ccy0 else (ccy1 if marker_y >= ccy1 else (ccy0 + ccy1) / 2)
                c_attach = fitz.Point(cax, cay)
                c_tip = (_closest_point_on_polygon(c_attach, polygon_points)
                         if polygon_points else fitz.Point(marker_x, marker_y))
                crossing_penalty = page_rect.width * page_rect.height * 0.001
                for (cl_a, cl_t) in committed_lines:
                    if _segments_intersect(c_attach, c_tip, cl_a, cl_t):
                        overlap += crossing_penalty

            if overlap < best_score:
                best_score = overlap
                best_rect = candidate

        if best_score == 0.0:
            break  # perfect placement found — no need to try larger distances

    # ── Fallback: if ALL positions intersect a forbidden rect, relax the hard
    # exclusion and just pick the minimum-overlap position (better than nothing).
    if best_rect is None and forbidden_rects:
        for dist_mult in (1.0, 1.4, 2.0, 2.8, 3.8, 5.0, 7.0):
            effective_dist = min_dist * dist_mult
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
                overlap = 0.0
                for placed in placed_boxes:
                    padded = placed + (-MARGIN, -MARGIN, MARGIN, MARGIN)
                    inter = candidate & padded
                    if not inter.is_empty:
                        overlap += inter.width * inter.height
                if committed_lines:
                    ccx0, ccy0, ccx1, ccy1 = candidate.x0, candidate.y0, candidate.x1, candidate.y1
                    cax = ccx0 if marker_x <= ccx0 else (ccx1 if marker_x >= ccx1 else (ccx0 + ccx1) / 2)
                    cay = ccy0 if marker_y <= ccy0 else (ccy1 if marker_y >= ccy1 else (ccy0 + ccy1) / 2)
                    c_attach = fitz.Point(cax, cay)
                    c_tip = (_closest_point_on_polygon(c_attach, polygon_points)
                             if polygon_points else fitz.Point(marker_x, marker_y))
                    crossing_penalty = page_rect.width * page_rect.height * 0.001
                    for (cl_a, cl_t) in committed_lines:
                        if _segments_intersect(c_attach, c_tip, cl_a, cl_t):
                            overlap += crossing_penalty
                if overlap < best_score:
                    best_score = overlap
                    best_rect = candidate
            if best_score == 0.0:
                break

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
        NUDGE = 6.0  # pt — how far inside the polygon the tip lands
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

    # ── Add the native PDF Callout FreeText annotation ────────────────────────
    # Requires PyMuPDF >= 1.25.3 (FreeTextCallout subtype added in that version)
    #
    # Confirmed by diagnostic grid (V04): text_color in the constructor controls
    # the /DA appearance stream, which PyMuPDF uses for text, box border AND the
    # callout arrow line — all three share the same color.  border_color and
    # set_colors() both raise ValueError for FreeText in this PyMuPDF build.
    # xref_set_key("C") + update() changes the BOX FILL, not the line color.
    # Conclusion: text_color is the single lever for arrow + border color.
    annot = page.add_freetext_annot(
        best_rect,
        text,
        fontsize=font_size,
        fontname="hebo",
        fill_color=(1, 0.85, 0),     # amber-yellow box background (richer than pure yellow on print)
        text_color=(0.75, 0, 0),     # dark crimson red → controls text, box border AND leader line (~6:1 contrast on amber)
        border_width=2.5,
        callout=[tip, attach],
        line_end=fitz.PDF_ANNOT_LE_NONE,
    )

    placed_boxes.append(best_rect)
    logging.info(f"✅ Callout placed at {best_rect} → tip ({marker_x:.1f}, {marker_y:.1f}), overlap={best_score:.0f}")

    # Return the leader-line endpoints so the caller can draw them as Line
    # annotations AFTER all FreeText annotations are placed.  PDF rendering is
    # always: content-stream first, then annotations in /Annots order.  Drawing
    # lines here (inside the function) — whether as content-stream shapes or as
    # annotations — would let later FreeText boxes paint over them.  Only by
    # adding Line annotations AFTER every FreeText annotation are the lines
    # guaranteed to render on top of all boxes in get_pixmap().
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
    logging.info(f"🧪 DIAG: rendered {len(VARIANTS)} callout variants at top-left")


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
        Annotated PDF as bytes
    """
    # Open PDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]  # First page

    logging.info(f"=" * 80)
    logging.info(f"PDF ANNOTATION")
    logging.info(f"=" * 80)

    # ── Floorplan specs ───────────────────────────────────────────────────────
    pdf_w = page.rect.width
    pdf_h = page.rect.height
    img_w = metadata['source_image']['width']
    img_h = metadata['source_image']['height']
    pts_per_mm = 2.8346
    px_per_pt_x = img_w / pdf_w
    px_per_pt_y = img_h / pdf_h

    logging.info(f"  PDF size   : {pdf_w:.1f} x {pdf_h:.1f} pt  ({pdf_w/pts_per_mm:.1f} x {pdf_h/pts_per_mm:.1f} mm)")
    logging.info(f"  Image size : {img_w} x {img_h} px")
    logging.info(f"  Px/pt ratio: {px_per_pt_x:.3f} x (horiz)  {px_per_pt_y:.3f} y (vert)")
    logging.info(f"  1 pt = {1/px_per_pt_x:.2f} px (horiz)  |  1 px = {px_per_pt_x:.3f} pt")
    logging.info(f"  Default callout: font=9pt ({9/pts_per_mm:.1f}mm)  box=130x? pt ({130/pts_per_mm:.1f}mm wide)")

    # ── Dynamic callout sizing from page dimensions + annotation density ──────
    # Step 1: scale up from A4 baseline for larger paper (A3, A1, A0…)
    A4_WIDTH_PT = 595.0
    page_scale = pdf_w / A4_WIDTH_PT  # 1.0 for A4, ~1.41 for A3, ~2.0 for A1

    # Step 2: count how many callouts we'll place to adjust for density
    n_callouts = sum(
        1 for obj in objects
        if obj.get("overlay") or obj.get("properties", {}).get("overlay")
        or obj.get("properties", {}).get("content") or obj.get("properties", {}).get("label")
    )
    n_callouts = max(n_callouts, 1)

    # Density factor: shrink when crowded, grow when sparse
    # 1-4 callouts → 1.0, 8 → ~0.85, 15 → ~0.72, 25 → ~0.63
    density_factor = min(1.0, (4.0 / n_callouts) ** 0.35) if n_callouts > 4 else 1.0

    # Base font: 10pt at A4 density=1, bold makes it legible at this size
    BASE_FONT = 10.0
    callout_font_size = round(max(8.0, BASE_FONT * page_scale * density_factor), 1)

    # box_width will be auto-sized per callout text (see place_callout_annotation)
    # but provide a max cap as % of page width (never more than 30% of page)
    callout_max_box_width = round(pdf_w * 0.30)

    logging.info(f"  Dynamic callout: font={callout_font_size}pt"
                 f"  page_scale={page_scale:.2f}  n_callouts={n_callouts}"
                 f"  density_factor={density_factor:.2f}  max_box_w={callout_max_box_width}pt")

    # Count object types
    type_counts: Dict[str, int] = {}
    for obj in objects:
        geo_type = obj.get("geometry", {}).get("type", "unknown")
        type_counts[geo_type] = type_counts.get(geo_type, 0) + 1
    logging.info(f"  Objects    : {len(objects)} total — " + ", ".join(f"{v}x {k}" for k, v in type_counts.items()))
    logging.info(f"=" * 80)

    # Detect whitespace trim offset (needed when PDF had margins that were cropped)
    trim_offset = detect_trim_offset(page, metadata)
    logging.info(f"Trim offset: left={trim_offset[0]:.1f}, top={trim_offset[1]:.1f} px")
    logging.info(f"=" * 80)

    # Process each object
    # pending_callouts collects (x_pdf, y_pdf, radius, text) for markers with
    # overlays.  Callout annotations are placed *after* all shapes are burned in
    # so the layout algorithm can avoid them properly.
    pending_callouts: List[Tuple[float, float, float, str]] = []
    shape_rects: List[fitz.Rect] = []   # bounding rects of all burned shapes
    polygon_rects: List[fitz.Rect] = [] # hard-exclusion zones (polygon fills)
    objects_drawn = 0
    for i, obj in enumerate(objects):
        try:
            logging.info(f"\n--- Object {i + 1}/{len(objects)} ---")
            obj_type = obj.get("properties", {}).get("type", "unknown")
            geometry = obj.get("geometry", {})
            geo_type = geometry.get("type")
            coordinates = geometry.get("coordinates", [])

            logging.info(f"Type: {obj_type}, Geometry: {geo_type}")

            if geo_type == "Polygon":
                config = ANNOTATION_CONFIG["polygon"].copy()
                overlay = obj.get("overlay") or obj.get("properties", {}).get("overlay")
                logging.info(f"   config: fill_opacity={config['fill_opacity']}, stroke_width={config['stroke_width']}, points={len(coordinates[0]) if coordinates else 0}")
                draw_polygon_on_pdf(page, coordinates, metadata, config, overlay, trim_offset, pending_callouts, shape_rects, polygon_rects)
                objects_drawn += 1

            elif geo_type == "Point":
                config = ANNOTATION_CONFIG["marker"].copy()
                label = obj.get("properties", {}).get("content") or obj.get("properties", {}).get("label")
                overlay = obj.get("overlay") or obj.get("properties", {}).get("overlay")
                draw_marker_on_pdf(page, coordinates, metadata, config, label, overlay, trim_offset, pending_callouts, shape_rects)
                objects_drawn += 1

            else:
                logging.warning(f"⚠️  Unknown type: {obj_type}")

        except Exception as e:
            logging.error(f"❌ Error drawing object {i + 1}: {str(e)}", exc_info=True)
            continue

    # ── Place deferred Callout annotations ──────────────────────────────────
    # Done after all burned-in shapes so the placement algorithm sees a clean
    # page with no shape outlines interfering with the overlap check.
    if pending_callouts:
        logging.info(f"\nPlacing {len(pending_callouts)} callout annotation(s)...")
        # Seed with shape bounding boxes so callouts won't overlap fills/circles.
        placed_boxes: List[fitz.Rect] = list(shape_rects)
        committed_lines: List[Tuple[fitz.Point, fitz.Point]] = []
        for item in pending_callouts:
            cx, cy, r, callout_text = item[:4]
            poly_pts = item[4] if len(item) > 4 else None
            try:
                result = place_callout_annotation(
                    page, cx, cy, r, callout_text, placed_boxes,
                    font_size=callout_font_size,
                    max_box_width=callout_max_box_width,
                    polygon_points=poly_pts,
                    forbidden_rects=polygon_rects,
                    committed_lines=committed_lines,
                )
                if result:
                    committed_lines.append(result)
            except Exception as e:
                logging.error(f"❌ Failed to place callout '{callout_text}': {e}", exc_info=True)

    logging.info(f"\n{'=' * 80}")
    logging.info(f"COMPLETE: {objects_drawn}/{len(objects)} objects drawn, {len(pending_callouts)} callout(s) placed")
    logging.info(f"{'=' * 80}\n")

    # Save to bytes
    output = io.BytesIO()
    doc.save(output)
    doc.close()

    return output.getvalue()


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
                logging.info(f"⚠️  file_url is not a PDF ({file_url}), deriving PDF URL: {derived_pdf_url}")
                file_url = derived_pdf_url

            logging.info(f"📝 Starting PDF annotation")
            logging.info(f"   PDF URL: {file_url}")
            logging.info(f"   Metadata URL: {metadata_url}")
            logging.info(f"   Objects to draw: {len(objects)}")

            # Download metadata
            logging.info("⬇️ Downloading metadata...")
            metadata_bytes = await download_file(metadata_url)
            metadata = json.loads(metadata_bytes.decode('utf-8'))
            logging.info(f"✅ Metadata loaded: {metadata.get('floorplan_id')}")

            # Download PDF
            logging.info("⬇️ Downloading PDF...")
            pdf_bytes = await download_file(file_url)
            logging.info(f"✅ PDF downloaded: {len(pdf_bytes)} bytes")

            # Annotate PDF
            logging.info("🎨 Annotating PDF...")
            annotated_pdf_bytes = annotate_pdf(pdf_bytes, objects, metadata)
            logging.info(f"✅ PDF annotated: {len(annotated_pdf_bytes)} bytes")

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

            logging.info("☁️ Uploading to Azure Blob Storage...")
            blob_service = BlobServiceClient.from_connection_string(connection_string)

            # Upload to 'annotated-pdfs' container
            container_name = "annotated-pdfs"
            try:
                container_client = blob_service.get_container_client(container_name)
                container_client.get_container_properties()
            except:
                # Create container if it doesn't exist
                container_client = blob_service.create_container(container_name, public_access="blob")
                logging.info(f"Created container: {container_name}")

            # Upload the annotated PDF
            blob_client = blob_service.get_blob_client(container_name, annotated_filename)
            blob_client.upload_blob(
                annotated_pdf_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="application/pdf")
            )

            # Generate the public URL
            annotated_pdf_url = f"https://blocksplayground.blob.core.windows.net/{container_name}/{annotated_filename}"

            logging.info(f"✅ Upload complete!")
            logging.info(f"   URL: {annotated_pdf_url}")

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
            logging.error(f"❌ Download error: {str(e)}")
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Failed to download file: {str(e)}"
                }),
                status_code=400,
                mimetype="application/json"
            )

        except Exception as e:
            logging.error(f"❌ Error annotating PDF: {str(e)}", exc_info=True)
            return func.HttpResponse(
                json.dumps({
                    "success": False,
                    "error": f"Error annotating PDF: {str(e)}",
                    "error_type": type(e).__name__
                }),
                status_code=500,
                mimetype="application/json"
            )
