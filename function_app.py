import azure.functions as func
import logging
import pypdfium2 as pdfium
from PIL import Image, ImageChops
from typing import List, Tuple, Dict
import io
import json
from datetime import datetime
from azure.storage.blob import BlobServiceClient, ContentSettings
import math
import os

app = func.FunctionApp()

# Import and register PDF annotation routes
import pdf_annotation
pdf_annotation.register_routes(app)


def pdf_to_images(pdf_content: bytes, scale: float = 2.0, max_dimension: int = 20000) -> List[Image.Image]:
    """
    Convert PDF bytes to a list of PIL Image objects using pypdfium2.
    Optimized for large single-page floor plans with extreme aspect ratios.

    Args:
        pdf_content: PDF file content as bytes
        scale: Scale factor for rendering (higher = better quality)
               2.0 = 144 DPI (standard)
               4.0 = 288 DPI (high quality)
               6.0 = 432 DPI (very high quality)
               8.0 = 576 DPI (extreme quality, large files)
        max_dimension: Maximum width or height in pixels before reducing scale
                       This prevents timeouts on extremely large dimensions (default 20000)

    Returns:
        List of PIL Image objects, one per page
    """
    try:
        logging.info(f"Starting PDF conversion at scale {scale}x")

        # Load PDF from bytes
        pdf = pdfium.PdfDocument(pdf_content)
        logging.info(f"PDF loaded: {len(pdf)} page(s)")

        images = []

        for page_index in range(len(pdf)):
            page = pdf[page_index]

            # Get page dimensions
            width = page.get_width()
            height = page.get_height()

            # Calculate target dimensions
            target_width = int(width * scale)
            target_height = int(height * scale)

            # Check if dimensions are too large
            if target_width > max_dimension or target_height > max_dimension:
                logging.warning(f"Page {page_index + 1} dimensions too large ({target_width}x{target_height}), reducing scale")

                # Calculate reduced scale to fit within max_dimension
                scale_factor = max_dimension / max(target_width, target_height)
                new_scale = scale * scale_factor

                target_width = int(width * new_scale)
                target_height = int(height * new_scale)

                logging.info(f"Adjusted scale to {new_scale:.2f}x, new dimensions: {target_width}x{target_height}")

            # Render page to PIL Image
            pil_image = page.render(
                scale=scale if target_width <= max_dimension and target_height <= max_dimension else new_scale,
                rotation=0,
                crop=(0, 0, 0, 0)
            ).to_pil()

            images.append(pil_image)

            logging.info(f"Page {page_index + 1}: {pil_image.width}x{pil_image.height} pixels, aspect ratio: {pil_image.width/pil_image.height:.2f}:1")

        pdf.close()

        return images

    except Exception as e:
        logging.error(f"Error converting PDF to images: {str(e)}")
        raise


class SimpleFloorplanTiler:
    """
    Simple CRS tiler for floorplans - treats image as flat 2D plane with pixel coordinates.
    Compatible with Leaflet's L.CRS.Simple (like MapTiler).
    Much simpler than Web Mercator - no geographic projection needed!
    """

    def __init__(self, tile_size: int = 256):
        self.tile_size = tile_size

    def tile_image(self,
                   source_img: Image.Image,
                   zoom_levels: List[int]) -> Dict[int, List[Tuple[int, int, Image.Image]]]:
        """
        Tile a floorplan image using Simple CRS (pixel coordinates)

        Args:
            source_img: PIL Image of the floorplan
            zoom_levels: List of zoom levels to generate (0 = most zoomed out)

        Returns:
            Dictionary mapping zoom level to list of (x, y, tile_image) tuples
        """
        if source_img.mode != 'RGBA':
            source_img = source_img.convert('RGBA')

        width, height = source_img.size
        max_zoom = max(zoom_levels)

        # Generate tiles for each zoom level
        pyramid = {}
        total_tiles = 0

        for zoom in sorted(zoom_levels, reverse=True):  # High to low
            tiles = self._generate_zoom_level(source_img, width, height, zoom, max_zoom)
            pyramid[zoom] = tiles
            tile_count = len(tiles)
            total_tiles += tile_count
            logging.info(f"Generated {tile_count} tiles for zoom level {zoom}")

        logging.info(f"Total tiles generated: {total_tiles} across {len(zoom_levels)} zoom levels")
        return pyramid

    def _generate_zoom_level(self,
                           source_img: Image.Image,
                           full_width: int,
                           full_height: int,
                           zoom: int,
                           max_zoom: int) -> List[Tuple[int, int, Image.Image]]:
        """Generate all tiles for a specific zoom level"""

        # Calculate scale factor for this zoom level
        # zoom 0 = most zoomed out, max_zoom = full resolution
        scale = 2 ** (zoom - max_zoom)

        # Calculate image dimensions at this zoom level
        scaled_width = int(full_width * scale)
        scaled_height = int(full_height * scale)

        # Resize image for this zoom level
        if zoom == max_zoom:
            scaled_img = source_img
        else:
            scaled_img = source_img.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)

        # Calculate number of tiles needed
        tiles_x = math.ceil(scaled_width / self.tile_size)
        tiles_y = math.ceil(scaled_height / self.tile_size)

        tiles = []

        # Generate each tile
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                tile_img = self._create_tile(scaled_img, tx, ty, scaled_width, scaled_height)
                if tile_img:
                    tiles.append((tx, ty, tile_img))

        # Release scaled image from memory if it's not the original
        if zoom != max_zoom:
            scaled_img.close()

        return tiles

    def _create_tile(self,
                    source_img: Image.Image,
                    tx: int, ty: int,
                    img_width: int, img_height: int) -> Image.Image:
        """Create a single tile from the source image"""

        # Calculate pixel bounds for this tile
        x1 = tx * self.tile_size
        y1 = ty * self.tile_size
        x2 = min(x1 + self.tile_size, img_width)
        y2 = min(y1 + self.tile_size, img_height)

        # Crop the tile from source image
        tile = source_img.crop((x1, y1, x2, y2))

        # If tile is smaller than tile_size (edge tiles), pad it with transparency
        if tile.width < self.tile_size or tile.height < self.tile_size:
            padded = Image.new('RGBA', (self.tile_size, self.tile_size), (0, 0, 0, 0))
            padded.paste(tile, (0, 0))
            return padded

        return tile


def generate_preview(image: Image.Image, max_width: int = 800) -> Image.Image:
    """
    Create low-res preview for initial load.

    Args:
        image: PIL Image to create preview from
        max_width: Maximum width for preview

    Returns:
        Preview image
    """
    ratio = image.width / image.height
    preview_width = min(max_width, image.width)
    preview_height = int(preview_width / ratio)
    return image.resize((preview_width, preview_height), Image.Resampling.LANCZOS)


def trim_whitespace(
    image: Image.Image,
    bg_color: Tuple[int, int, int] = (255, 255, 255),
    tolerance: int = 10,
    padding: int = 20
) -> Image.Image:
    """
    Auto-crop uniform background margins (e.g., white) from the image.
    Adds a small padding back to avoid cutting content too tightly.

    Args:
        image: PIL Image to crop
        bg_color: Background color to treat as whitespace (default white)
        tolerance: 0-255 threshold for considering pixels as background
        padding: Pixels to keep around detected content box

    Returns:
        Cropped PIL Image (or original if no content box found)
    """
    try:
        if image.mode != 'RGB':
            img = image.convert('RGB')
        else:
            img = image

        # Compute difference from a solid background image
        bg = Image.new('RGB', img.size, bg_color)
        diff = ImageChops.difference(img, bg).convert('L')
        # Threshold the difference to build a mask of non-background pixels
        mask = diff.point(lambda p: 255 if p > tolerance else 0)
        bbox = mask.getbbox()

        if not bbox:
            logging.info("Whitespace trim: no content bbox found; returning original image")
            return image

        # Expand bbox by padding, clamped to image bounds
        left, top, right, bottom = bbox
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(img.width, right + padding)
        bottom = min(img.height, bottom + padding)

        if left == 0 and top == 0 and right == img.width and bottom == img.height:
            logging.info("Whitespace trim: bbox equals full image; nothing to crop")
            return image

        cropped = img.crop((left, top, right, bottom))
        logging.info(f"Whitespace trim: cropped from {img.width}x{img.height} to {cropped.width}x{cropped.height}")
        return cropped
    except Exception as e:
        logging.warning(f"Whitespace trim failed: {e}")
        return image


def create_metadata(image: Image.Image, max_zoom: int, floorplan_id: str, tile_size: int, min_zoom: int = 0, zoom_levels: List[int] = None) -> dict:
    """
    Generate metadata for Web Mercator tile consumption.

    Args:
        image: PIL Image
        max_zoom: Maximum zoom level
        floorplan_id: Unique identifier for this floor plan
        tile_size: Size of tiles in pixels
        min_zoom: Minimum zoom level
        zoom_levels: List of actual zoom levels generated

    Returns:
        Metadata dictionary compatible with Web Mercator tiling
    """
    # Simple CRS bounds - just pixel coordinates (like MapTiler)
    # No geographic projection needed!
    image_bounds = [[0, 0], [image.height, image.width]]  # [[y_min, x_min], [y_max, x_max]]

    return {
        "floorplan_id": floorplan_id,
        "source_image": {
            "width": image.width,
            "height": image.height,
            "format": "RGBA"
        },
        "tile_size": tile_size,
        "max_zoom": max_zoom,
        "min_zoom": max(0, min_zoom),
        "zoom_levels": zoom_levels or list(range(max(0, min_zoom), max_zoom + 1)),
        "bounds": image_bounds,  # Simple pixel coordinate bounds
        "coordinate_system": "Simple CRS (L.CRS.Simple) - pixel coordinates, compatible with MapTiler",
        "center": [image.height / 2, image.width / 2],  # Center in pixel coordinates [y, x]
        "created_at": datetime.utcnow().isoformat(),
        "tile_format": "png",
        "total_tiles": None,  # Will be filled by caller
        "usage_notes": {
            "leaflet_crs": "Use L.CRS.Simple for flat floorplan display",
            "tile_url_template": "{baseUrl}/{z}/{x}/{y}.png",
            "bounds_format": "Geographic coordinates (lat/lon)"
        }
    }


def upload_tiles_to_blob(
    pyramid: Dict[int, List[Tuple[int, int, Image.Image]]],
    preview: Image.Image,
    metadata: dict,
    floorplan_id: str,
    original_blob_name: str,
    connection_string: str,
    container: str = "floor-plans",
    base_image: Image.Image | None = None,
    base_image_data: bytes | None = None,
    base_image_format: str = "png"
):
    """
    Upload entire tile pyramid to Azure Blob Storage.
    Structure: floor-plans/{floorplan-id}/
                   ├── {floorplan-id}.pdf (archived original PDF - handled elsewhere)
                   ├── metadata.json
                   ├── preview.jpg
                   ├── base.png (full-resolution rendered image used for tiling) [optional]
                   └── tiles/{z}/{x}/{y}.png

    Args:
        pyramid: Dictionary of zoom level to tiles
        preview: Preview image
        metadata: Metadata dictionary
        floorplan_id: Unique identifier
        original_blob_name: Original blob name (e.g., "floor-plans/MyPlan.pdf")
        connection_string: Azure Storage connection string
        container: Container name (default: "floor-plans")
    """
    logging.info(f"Uploading tiles to blob storage: {container}/{floorplan_id}/")

    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service.get_container_client(container)

    # Container should already exist (floor-plans)
    try:
        container_client.get_container_properties()
        logging.info(f"Using existing container: {container}")
    except Exception as e:
        logging.warning(f"Container check failed: {str(e)}")

    # Note: Original PDF archiving is handled in the main function using in-memory bytes
    # to avoid async copy races and permissions issues.

    # Upload metadata
    metadata_blob = f"{floorplan_id}/metadata.json"
    container_client.upload_blob(
        metadata_blob,
        json.dumps(metadata, indent=2),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json")
    )
    logging.info(f"Uploaded metadata: {metadata_blob}")

    # Upload preview
    preview_bytes = io.BytesIO()
    preview.save(preview_bytes, format='JPEG', quality=75, optimize=True)
    preview_bytes.seek(0)
    container_client.upload_blob(
        f"{floorplan_id}/preview.jpg",
        preview_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="image/jpeg")
    )
    logging.info(f"Uploaded preview image")

    # Upload optimized base image (optional)
    if base_image_data is not None:
        try:
            base_filename = f"base-image.{base_image_format}"
            content_type = f"image/{base_image_format}" if base_image_format != "webp" else "image/webp"

            container_client.upload_blob(
                f"{floorplan_id}/{base_filename}",
                base_image_data,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )
            size_mb = len(base_image_data) / (1024*1024)
            logging.info(f"Uploaded optimized base image: {base_filename} ({size_mb:.2f} MB, {base_image_format.upper()})")
        except Exception as be:
            logging.warning(f"Failed to upload base image: {be}")

    # Upload all tiles
    total_tiles = sum(len(tiles) for tiles in pyramid.values())
    uploaded = 0

    for zoom, tiles in pyramid.items():
        for x, y, tile_image in tiles:
            tile_bytes = io.BytesIO()
            # Use balanced compression (6) for good quality with smaller files
            # compress_level 6 = balanced quality/size (default is 6)
            tile_image.save(tile_bytes, format='PNG', compress_level=6)
            tile_bytes.seek(0)

            # Leaflet standard: {z}/{x}/{y}.png
            blob_path = f"{floorplan_id}/tiles/{zoom}/{x}/{y}.png"
            container_client.upload_blob(
                blob_path,
                tile_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="image/png")
            )

            uploaded += 1
            if uploaded % 10 == 0:
                logging.info(f"Upload progress: {uploaded}/{total_tiles} tiles")

    logging.info(f"✅ Successfully uploaded {total_tiles} tiles for {floorplan_id}")


def extract_floorplan_id(blob_name: str) -> str:
    """
    Extract floor plan ID from blob name.
    Example: floor-plans/myplan.pdf -> myplan
    """
    filename = blob_name.split('/')[-1]
    return filename.rsplit('.', 1)[0]

@app.route(route="process-floorplan", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def blocks_floorplan_tiler_service(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("HTTP POST request received for floorplan processing")

    # Wrap everything in a try-catch to ensure we always return a proper HTTP response
    try:
        # Parse request body
        try:
            req_body = req.get_json()
        except ValueError as e:
            logging.error(f"Invalid JSON in request: {str(e)}")
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Invalid JSON in request body"}),
                status_code=400,
                mimetype="application/json"
            )

        file_url = req_body.get('file_url')
        floorplan_name = req_body.get('floorplan_name')  # Optional custom name

        if not file_url:
            return func.HttpResponse(
                json.dumps({"success": False, "error": "Missing 'file_url' in request body"}),
                status_code=400,
                mimetype="application/json"
            )

        logging.info(f"Processing PDF from URL: {file_url}")

        # Download the PDF from Azure Blob Storage or URL
        try:
            # Check if it's an Azure Blob Storage URL
            if 'blob.core.windows.net' in file_url:
                # Use Azure SDK to download from blob storage
                connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
                if not connection_string:
                    return func.HttpResponse(
                        json.dumps({"success": False, "error": "Azure Storage connection string not configured"}),
                        status_code=500,
                        mimetype="application/json"
                    )

                # Parse the blob URL to extract container and blob name
                from urllib.parse import urlparse
                parsed_url = urlparse(file_url)
                # URL format: https://<account>.blob.core.windows.net/<container>/<blob-path>
                path_parts = parsed_url.path.lstrip('/').split('/', 1)
                container_name = path_parts[0]
                blob_name = path_parts[1] if len(path_parts) > 1 else ''

                logging.info(f"Downloading from Azure Blob: container={container_name}, blob={blob_name}")

                blob_service = BlobServiceClient.from_connection_string(connection_string)
                blob_client = blob_service.get_blob_client(container_name, blob_name)
                file_content = blob_client.download_blob().readall()
                logging.info(f"Downloaded PDF from blob storage: {len(file_content)} bytes")
            else:
                # Download from external URL
                import urllib.request
                with urllib.request.urlopen(file_url) as response:
                    file_content = response.read()
                logging.info(f"Downloaded PDF from URL: {len(file_content)} bytes")
        except Exception as download_error:
            logging.error(f"Error downloading file: {str(download_error)}", exc_info=True)
            return func.HttpResponse(
                json.dumps({"success": False, "error": f"Failed to download file: {str(download_error)}"}),
                status_code=400,
                mimetype="application/json"
            )

        # Extract filename from URL or use provided name
        if not floorplan_name:
            from urllib.parse import urlparse
            parsed_url = urlparse(file_url)
            floorplan_name = parsed_url.path.split('/')[-1]
            if not floorplan_name.lower().endswith('.pdf'):
                floorplan_name = 'floorplan.pdf'

        # Create a mock blob name for compatibility
        myblob_name = f"floor-plans/{floorplan_name}"

        # ============================================================
        # 🚀 PRODUCTION MODE - HIGH QUALITY TILING SETTINGS
        # ============================================================

        # 🎨 QUALITY SETTINGS (Balanced for performance):
        PDF_SCALE = 15.0         # 1080 DPI - Good quality, won't crash
        MAX_DIMENSION = 30000    # 30K pixels max dimension

        # 🗺️ TILING CONFIGURATION - DEEP ZOOM MODE:
        MAX_ZOOM_LIMIT = 15      # Maximum zoom levels allowed
        FORCED_MAX_Z_ENV = 10    # Allow zoom up to level 10 (will upscale beyond native)
        TILE_SIZE_ENV = 512      # 512px tiles for optimal balance
        MIN_ZOOM_ENV = 0         # Start from zoom level 0

        # ✅ Deep zoom with upscaling beyond native resolution
        # Native res at zoom ~6-7, then upscales for zoom 8-10
        # ============================================================

        # Check if the file is a PDF
        if not floorplan_name.lower().endswith('.pdf'):
            return func.HttpResponse(
                json.dumps({"success": False, "error": "File must be a PDF"}),
                status_code=400,
                mimetype="application/json"
            )

        # Guard: Only process PDFs uploaded at the container root to avoid re-processing
        # when we copy the PDF into a subfolder after processing.
        try:
            container_and_rest = myblob_name.split('/', 1)  # ['floor-plans', 'foo.pdf'] or ['floor-plans', 'id/foo.pdf']
            relative_path = container_and_rest[1] if len(container_and_rest) > 1 else myblob_name
            if '/' in relative_path:
                logging.info(f"Ignoring nested PDF '{relative_path}' to prevent re-processing loop.")
                return func.HttpResponse(
                    json.dumps({"success": True, "message": "Skipped nested PDF to prevent re-processing"}),
                    status_code=200,
                    mimetype="application/json"
                )
        except Exception as _:
            # If parsing fails for any reason, continue (best-effort guard)
            pass

        logging.info(f"Processing PDF file: {myblob_name}")
        # Validate TILE_SIZE to supported values
        if TILE_SIZE_ENV not in (128, 256, 512, 1024):
            logging.warning(f"Unsupported TILE_SIZE={TILE_SIZE_ENV}; defaulting to 256")
            TILE_SIZE_ENV = 256

        logging.info(
            "Configuration overrides → "
            f"PDF_SCALE={PDF_SCALE}, MAX_DIMENSION={MAX_DIMENSION}, "
            f"MAX_ZOOM_LIMIT={MAX_ZOOM_LIMIT}, FORCED_MAX_Z={FORCED_MAX_Z_ENV}, "
            f"TILE_SIZE={TILE_SIZE_ENV}, MIN_ZOOM={MIN_ZOOM_ENV}"
        )

        # File content already downloaded in HTTP trigger
        logging.info(f"Processing {len(file_content)} bytes from PDF file")

        # 1. Convert PDF to PNG (single page expected)
        # Higher scale = better quality at max zoom
        images = pdf_to_images(file_content, scale=PDF_SCALE, max_dimension=MAX_DIMENSION)

        if len(images) == 0:
            logging.error("No images generated from PDF")
            return func.HttpResponse(
                json.dumps({"error": "No images generated from PDF"}),
                status_code=500,
                mimetype="application/json"
            )

        # Use first page (floor plans should be single page)
        floor_plan_image = images[0]
        logging.info(f"Floor plan dimensions (pre-trim): {floor_plan_image.width}x{floor_plan_image.height} pixels")

        # Release extra images from memory immediately
        if len(images) > 1:
            for img in images[1:]:
                img.close()
            images = [floor_plan_image]

        # Optional: auto-trim white margins around the plan to reduce empty space/tiles
        floor_plan_image = trim_whitespace(floor_plan_image, bg_color=(255, 255, 255), tolerance=10, padding=20)
        logging.info(f"Floor plan dimensions (post-trim): {floor_plan_image.width}x{floor_plan_image.height} pixels")

        # 2. Set zoom levels for Leaflet tiles
        # Always produce up to a fixed max zoom for Leaflet folder structure (z/x/y),
        # independent of the native resolution. This adds more zoom steps but does not
        # add new detail beyond the image's native pixels.
        FORCED_MAX_Z = max(0, min(FORCED_MAX_Z_ENV, MAX_ZOOM_LIMIT))
        max_zoom = FORCED_MAX_Z
        min_zoom = max(0, min(MIN_ZOOM_ENV, max_zoom))
        total_levels = (max_zoom - min_zoom + 1)
        logging.info(f"Using Leaflet zoom levels: {min_zoom}-{max_zoom} (total {total_levels})")

        # Log native tile density at highest zoom for visibility
        tile_size = TILE_SIZE_ENV
        native_tiles_x = math.ceil(floor_plan_image.width / tile_size)
        native_tiles_y = math.ceil(floor_plan_image.height / tile_size)
        native_total_tiles = native_tiles_x * native_tiles_y
        logging.info(
            "Max-zoom native tile grid: "
            f"{native_tiles_x}x{native_tiles_y} (total {native_total_tiles}) at {floor_plan_image.width}x{floor_plan_image.height}px"
        )

        # 3. Generate tile pyramid using Simple CRS (like MapTiler) with optimized quality
        logging.info("🗺️ Generating Simple CRS tile pyramid with ultra-high quality...")

        # Create zoom level list from min to max
        zoom_levels = list(range(min_zoom, max_zoom + 1))

        # Initialize the Simple CRS floorplan tiler with optimized settings
        floorplan_tiler = SimpleFloorplanTiler(tile_size=tile_size)

        # Generate tiles using Simple CRS (pixel-based, no geographic projection)
        pyramid = floorplan_tiler.tile_image(floor_plan_image, zoom_levels)
        total_tiles = sum(len(tiles) for tiles in pyramid.values())
        logging.info(f"Generated {total_tiles} high-quality tiles across {len(pyramid)} zoom levels")

        # 4. Generate preview image with optimal compression
        logging.info("Generating preview image...")
        preview = generate_preview(floor_plan_image, max_width=800)

        # Save optimized base image for reference
        base_image_buffer = io.BytesIO()
        try:
            floor_plan_image.save(base_image_buffer, format='WebP', quality=85, method=4)
            base_image_format = 'webp'
            logging.info("✅ Using WebP format for base image compression")
        except Exception:
            base_image_buffer = io.BytesIO()
            floor_plan_image.save(base_image_buffer, format='PNG', compress_level=6, optimize=True)
            base_image_format = 'png'
            logging.info("✅ Using PNG format for base image compression")

        base_image_data = base_image_buffer.getvalue()
        base_image_size_mb = len(base_image_data) / (1024*1024)
        logging.info(f"📦 Base image compressed to: {base_image_size_mb:.2f} MB")

        # 5. Create metadata with high-quality settings
        floorplan_id = extract_floorplan_id(myblob_name)
        metadata = create_metadata(
            floor_plan_image,
            max_zoom,
            floorplan_id,
            tile_size=tile_size,
            min_zoom=min_zoom,
            zoom_levels=zoom_levels
        )
        metadata["total_tiles"] = total_tiles
        metadata["quality_settings"] = {
            "pdf_scale": PDF_SCALE,
            "max_dimension": MAX_DIMENSION,
            "dpi": PDF_SCALE * 72,
            "base_image_format": base_image_format,
            "base_image_size_mb": round(base_image_size_mb, 2)
        }
        logging.info(f"Created Web Mercator metadata for ultra-high quality floor plan: {floorplan_id}")

        # 6. Upload to blob storage
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            logging.error("Azure Storage connection string not found in environment")
            return func.HttpResponse(
                json.dumps({"error": "Azure Storage connection string not configured"}),
                status_code=500,
                mimetype="application/json"
            )

        logging.info("Uploading high-quality tiles and assets to blob storage...")
        upload_tiles_to_blob(
            pyramid=pyramid,
            preview=preview,
            metadata=metadata,
            floorplan_id=floorplan_id,
            original_blob_name=myblob_name,
            connection_string=connection_string,
            container="floor-plans",
            base_image=floor_plan_image,
            base_image_data=base_image_data,
            base_image_format=base_image_format
        )

        # Release memory: close images and clear pyramid after upload
        preview.close()
        for zoom_tiles in pyramid.values():
            for _, _, tile_img in zoom_tiles:
                tile_img.close()
        pyramid.clear()
        logging.info("✅ Cleaned up image memory after upload")

        # 7. Archive the original PDF and clean up
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        source_container = "floor-plans"

        # Store a copy of the original PDF under {floorplan_id}/{floorplan_id}.pdf
        try:
            dest_blob_name = f"{floorplan_id}/{floorplan_id}.pdf"
            dest_client = blob_service.get_blob_client(source_container, dest_blob_name)
            content_settings = ContentSettings(content_type="application/pdf")
            dest_client.upload_blob(file_content, overwrite=True, content_settings=content_settings)
            logging.info(f"Archived original PDF at: {dest_blob_name}")
        except Exception as copy_err:
            logging.warning(f"Could not store archived PDF copy: {str(copy_err)}")

        # Delete the original root-level PDF (only if it was uploaded at root)
        try:
            src_relative = relative_path
            if '/' not in src_relative:
                src_client = blob_service.get_blob_client(source_container, src_relative)
                src_client.delete_blob()
                logging.info(f"Deleted original root PDF: {src_relative}")
        except Exception as del_err:
            logging.warning(f"Could not delete original PDF: {str(del_err)}")

        logging.info(f"🚀 Successfully created ULTRA-HIGH QUALITY tiled floor plan: {floorplan_id}")
        logging.info(f"   📐 Dimensions: {floor_plan_image.width}x{floor_plan_image.height}px")
        logging.info(f"   🎨 Quality: {PDF_SCALE * 72:.0f} DPI (PDF_SCALE={PDF_SCALE})")
        logging.info(f"   📦 Base image: {base_image_size_mb:.2f} MB ({base_image_format.upper()})")
        logging.info(f"   🗺️ Zoom levels: {total_levels} ({min_zoom}-{max_zoom})")
        logging.info(f"   🏗️ Total tiles: {total_tiles}")
        logging.info(f"   📏 Tile size: {tile_size}px")
        logging.info(f"   🌐 Coordinate system: Simple CRS (L.CRS.Simple)")
        logging.info(f"   💾 Storage: floor-plans/{floorplan_id}/")

        # Return success response
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "floorplan_id": floorplan_id,
                "dimensions": {
                    "width": floor_plan_image.width,
                    "height": floor_plan_image.height
                },
                "quality": {
                    "dpi": int(PDF_SCALE * 72),
                    "base_image_size_mb": round(base_image_size_mb, 2),
                    "format": base_image_format.upper()
                },
                "tiles": {
                    "total": total_tiles,
                    "zoom_levels": total_levels,
                    "min_zoom": min_zoom,
                    "max_zoom": max_zoom,
                    "tile_size": tile_size
                },
                "urls": {
                    "metadata": f"https://blocksplayground.blob.core.windows.net/floor-plans/{floorplan_id}/metadata.json",
                    "preview": f"https://blocksplayground.blob.core.windows.net/floor-plans/{floorplan_id}/preview.png",
                    "tiles": f"https://blocksplayground.blob.core.windows.net/floor-plans/{floorplan_id}/tiles/{{z}}/{{x}}/{{y}}.png"
                }
            }),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as outer_error:
        # Final catch-all for any unexpected errors
        logging.error(f"❌ Unexpected error: {str(outer_error)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "success": False,
                "error": f"Unexpected error: {str(outer_error)}",
                "error_type": type(outer_error).__name__
            }),
            status_code=500,
            mimetype="application/json"
        )
