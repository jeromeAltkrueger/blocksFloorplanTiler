"""
PDF Annotation Module
Handles annotating PDFs with shapes and markers from Leaflet drawings.
"""

import azure.functions as func
import logging
import fitz  # PyMuPDF for PDF annotation
from typing import List, Dict, Any, Tuple
import io
import json
from datetime import datetime
from azure.storage.blob import BlobServiceClient, ContentSettings
import os
import httpx


# ==========================================
# PDF ANNOTATION CONFIGURATION
# ==========================================

# Annotation styling - easily adjustable
ANNOTATION_CONFIG = {
    "polygon": {
        "fill_color": (1, 0, 0),      # Red (RGB normalized 0-1)
        "fill_opacity": 0.3,           # 30% opacity for fill
        "stroke_color": (1, 0, 0),     # Red border
        "stroke_width": 2,             # Border width in points
        "stroke_opacity": 0.8          # 80% opacity for border
    },
    "marker": {
        "fill_color": (1, 0, 0),       # Red
        "fill_opacity": 0.7,           # 70% opacity
        "radius": 8,                   # Circle radius in points
        "stroke_color": (0.5, 0, 0),   # Dark red border
        "stroke_width": 1.5
    },
    "square": {
        "fill_color": (1, 0, 0),       # Red
        "fill_opacity": 0.3,
        "stroke_color": (1, 0, 0),
        "stroke_width": 2,
        "stroke_opacity": 0.8
    },
    "text": {
        "font_size": 10,               # Font size in points
        "font_color": (1, 0, 0),       # Red text
        "background_color": (1, 1, 1), # White background
        "background_opacity": 0.8,     # 80% opaque background
        "padding": 2                   # Padding around text
    }
}


# ==========================================
# PDF ANNOTATION HELPER FUNCTIONS
# ==========================================

def leaflet_to_pdf_coords(leaflet_coords: List[float], metadata: Dict[str, Any]) -> Tuple[float, float]:
    """
    Convert Leaflet Simple CRS coordinates to PDF pixel coordinates.

    Args:
        leaflet_coords: [lat, lon] from Leaflet (Simple CRS format)
        metadata: Metadata containing bounds and image dimensions

    Returns:
        (x, y) tuple in PDF pixel coordinates
    """
    lat, lon = leaflet_coords

    # Extract bounds and dimensions from metadata
    bounds = metadata["bounds"]  # [[lat_min, lon_min], [lat_max, lon_max]]
    width = metadata["source_image"]["width"]
    height = metadata["source_image"]["height"]

    # Bounds format: [[south_west], [north_east]]
    lat_min, lon_min = bounds[0]
    lat_max, lon_max = bounds[1]

    # Map latitude (y-axis) - note: PDF y=0 is at top, may need inversion
    # In Simple CRS with bounds [[0,0], [height, width]], lat maps to y
    if lat_max != lat_min:
        y = ((lat - lat_min) / (lat_max - lat_min)) * height
    else:
        y = 0

    # Map longitude (x-axis)
    if lon_max != lon_min:
        x = ((lon - lon_min) / (lon_max - lon_min)) * width
    else:
        x = 0

    return (x, y)


def draw_polygon_on_pdf(page: fitz.Page, coordinates: List[List[List[float]]],
                       metadata: Dict[str, Any], config: Dict[str, Any]) -> None:
    """
    Draw a filled polygon on the PDF page.

    Args:
        page: PyMuPDF page object
        coordinates: GeoJSON polygon coordinates [[[lon, lat], [lon, lat], ...]]
        metadata: Metadata for coordinate transformation
        config: Styling configuration
    """
    # GeoJSON polygons: coordinates[0] is outer ring
    outer_ring = coordinates[0]

    # Convert Leaflet coords to PDF coords
    # Note: GeoJSON uses [lon, lat] but Leaflet Simple CRS uses [lat, lon]
    # Based on user's example, we'll treat them as [lat, lon]
    pdf_points = []
    for point in outer_ring:
        lat, lon = point[0], point[1] if len(point) > 1 else point[0]
        x, y = leaflet_to_pdf_coords([lat, lon], metadata)
        pdf_points.append(fitz.Point(x, y))

    # Draw filled polygon
    if len(pdf_points) >= 3:
        # Create the shape
        shape = page.new_shape()

        # Draw polygon with fill
        shape.draw_polyline(pdf_points)
        shape.finish(
            fill=config["fill_color"],
            color=config["stroke_color"],
            width=config["stroke_width"],
            fill_opacity=config["fill_opacity"],
            stroke_opacity=config.get("stroke_opacity", 1.0)
        )

        # Commit the shape to the page
        shape.commit()


def draw_marker_on_pdf(page: fitz.Page, coordinates: List[float],
                       metadata: Dict[str, Any], config: Dict[str, Any],
                       label: str = None) -> None:
    """
    Draw a circular marker on the PDF page.

    Args:
        page: PyMuPDF page object
        coordinates: [lat, lon] point coordinates
        metadata: Metadata for coordinate transformation
        config: Styling configuration
        label: Optional text label to draw
    """
    # Convert to PDF coordinates
    x, y = leaflet_to_pdf_coords(coordinates, metadata)

    # Draw circle
    shape = page.new_shape()
    radius = config["radius"]

    # Draw filled circle
    shape.draw_circle(fitz.Point(x, y), radius)
    shape.finish(
        fill=config["fill_color"],
        color=config.get("stroke_color", config["fill_color"]),
        width=config.get("stroke_width", 1),
        fill_opacity=config["fill_opacity"]
    )
    shape.commit()

    # Draw label if provided
    if label:
        text_config = ANNOTATION_CONFIG["text"]
        draw_text_on_pdf(page, [x, y + radius + 5], label, text_config)


def draw_square_on_pdf(page: fitz.Page, coordinates: List[List[List[float]]],
                      metadata: Dict[str, Any], config: Dict[str, Any]) -> None:
    """
    Draw a filled square/rectangle on the PDF page.

    Args:
        page: PyMuPDF page object
        coordinates: Rectangle coordinates (4 corner points)
        metadata: Metadata for coordinate transformation
        config: Styling configuration
    """
    # Treat squares the same as polygons
    draw_polygon_on_pdf(page, coordinates, metadata, config)


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
    # Open PDF with PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Get first page (assuming single-page floorplan)
    page = doc[0]

    logging.info(f"PDF page size: {page.rect.width} x {page.rect.height}")
    logging.info(f"Source image size: {metadata['source_image']['width']} x {metadata['source_image']['height']}")

    # Process each object
    for obj in objects:
        try:
            obj_type = obj.get("properties", {}).get("type", "unknown")
            geometry = obj.get("geometry", {})
            geo_type = geometry.get("type")
            coordinates = geometry.get("coordinates", [])

            logging.info(f"Drawing {obj_type} ({geo_type})")

            if obj_type == "rectangle" or obj_type == "square" or geo_type == "Polygon":
                # Draw polygon/rectangle
                config = ANNOTATION_CONFIG.get("square" if obj_type == "square" else "polygon")
                draw_polygon_on_pdf(page, coordinates, metadata, config)

            elif obj_type == "marker" or geo_type == "Point":
                # Draw marker
                config = ANNOTATION_CONFIG["marker"]
                label = obj.get("properties", {}).get("content") or obj.get("properties", {}).get("label")
                draw_marker_on_pdf(page, coordinates, metadata, config, label)

            else:
                logging.warning(f"Unknown object type: {obj_type} (geometry: {geo_type})")

        except Exception as e:
            logging.error(f"Error drawing object: {str(e)}", exc_info=True)
            continue

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
            connection_string = os.environ.get("blocksplayground_STORAGE")
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
