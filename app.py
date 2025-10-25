"""
FastAPI application for floorplan PDF tiling service.
Converted from Azure Functions for deployment to Azure Container Apps.
"""
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging
import fitz  # PyMuPDF
from PIL import Image, ImageChops
from typing import List, Tuple, Dict, Optional
import io
import json
from datetime import datetime
from azure.storage.blob import BlobServiceClient, ContentSettings
import math
import os
import uvicorn
import uuid
import threading
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Disable PIL decompression bomb check for large floor plans
Image.MAX_IMAGE_PIXELS = None

# Job status tracking
class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# In-memory job store (for simple implementation)
jobs_store = {}
jobs_lock = threading.Lock()

# Initialize FastAPI app
app = FastAPI(
    title="Blocks Floorplan Tiler Service",
    description="High-quality PDF floorplan to tile pyramid converter for Leaflet/MapTiler",
    version="2.0.0"
)

# Request model
class ProcessFloorplanRequest(BaseModel):
    file_url: str


def pdf_to_images(pdf_content: bytes, scale: float = 2.0, max_dimension: int = 20000) -> List[Image.Image]:
    """
    Convert PDF bytes to a list of PIL Image objects using PyMuPDF (fitz).
    Optimized for large single-page floor plans with extreme aspect ratios.
    
    Args:
        pdf_content: PDF file content as bytes
        scale: Scale factor for rendering (higher = better quality)
               2.0 = 144 DPI (standard)
               4.0 = 288 DPI (high quality)
               6.0 = 432 DPI (very high quality)
               15.0 = 1080 DPI (extreme quality)
        max_dimension: Maximum width or height in pixels before reducing scale
                       This prevents timeouts on extremely large dimensions (default 20000)
    
    Returns:
        List of PIL Image objects, one per page
    """
    try:
        logger.info(f"Starting PDF conversion at scale {scale}x")
        
        # Open PDF from bytes
        pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
        logger.info(f"PDF loaded: {pdf_document.page_count} page(s)")
        
        images = []
        
        for page_num in range(pdf_document.page_count):
            page = pdf_document[page_num]
            
            # Get page dimensions in points
            rect = page.rect
            width_pt = rect.width
            height_pt = rect.height
            
            # Calculate target dimensions
            target_width = int(width_pt * scale)
            target_height = int(height_pt * scale)
            
            # Check if dimensions are too large
            actual_scale = scale
            if target_width > max_dimension or target_height > max_dimension:
                logger.warning(f"Page {page_num + 1} dimensions too large ({target_width}x{target_height}), reducing scale")
                
                # Calculate reduced scale to fit within max_dimension
                scale_factor = max_dimension / max(target_width, target_height)
                actual_scale = scale * scale_factor
                
                target_width = int(width_pt * actual_scale)
                target_height = int(height_pt * actual_scale)
                
                logger.info(f"Adjusted scale to {actual_scale:.2f}x, new dimensions: {target_width}x{target_height}")
            
            # Create transformation matrix for scaling
            mat = fitz.Matrix(actual_scale, actual_scale)
            
            # Render page to pixmap (high quality)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Convert pixmap to PIL Image
            img_data = pix.tobytes("png")
            pil_image = Image.open(io.BytesIO(img_data))
            
            images.append(pil_image)
            
            logger.info(f"Page {page_num + 1}: {pil_image.width}x{pil_image.height} pixels, aspect ratio: {pil_image.width/pil_image.height:.2f}:1")
        
        pdf_document.close()
        
        return images
    
    except Exception as e:
        logger.error(f"Error converting PDF to images: {str(e)}")
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
            logger.info(f"Generated {tile_count} tiles for zoom level {zoom}")
        
        logger.info(f"Total tiles generated: {total_tiles} across {len(zoom_levels)} zoom levels")
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
            logger.info("Whitespace trim: no content bbox found; returning original image")
            return image

        # Expand bbox by padding, clamped to image bounds
        left, top, right, bottom = bbox
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(img.width, right + padding)
        bottom = min(img.height, bottom + padding)

        if left == 0 and top == 0 and right == img.width and bottom == img.height:
            logger.info("Whitespace trim: bbox equals full image; nothing to crop")
            return image

        cropped = img.crop((left, top, right, bottom))
        logger.info(f"Whitespace trim: cropped from {img.width}x{img.height} to {cropped.width}x{cropped.height}")
        return cropped
    except Exception as e:
        logger.warning(f"Whitespace trim failed: {e}")
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
    container: str = "blocks",
    base_image: Image.Image | None = None,
    base_image_data: bytes | None = None,
    base_image_format: str = "png"
):
    """
    Upload entire tile pyramid to Azure Blob Storage.
    Structure: blocks/floorplans/{floorplan-id}/
                   ├── metadata.json
                   ├── preview.jpg
                   ├── base.png (full-resolution rendered image used for tiling) [optional]
                   └── tiles/{z}/{x}/{y}.png
    
    Args:
        pyramid: Dictionary of zoom level to tiles
        preview: Preview image
        metadata: Metadata dictionary
        floorplan_id: Unique identifier
        original_blob_name: Original blob name
        connection_string: Azure Storage connection string
        container: Container name (default: "blocks")
    """
    logger.info(f"Uploading tiles to blob storage: {container}/floorplans/{floorplan_id}/")
    
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service.get_container_client(container)
    
    # Container should already exist (floor-plans)
    try:
        container_client.get_container_properties()
        logger.info(f"Using existing container: {container}")
    except Exception as e:
        logger.warning(f"Container check failed: {str(e)}")
    
    # Upload metadata
    metadata_blob = f"floorplans/{floorplan_id}/metadata.json"
    container_client.upload_blob(
        metadata_blob, 
        json.dumps(metadata, indent=2),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json")
    )
    logger.info(f"Uploaded metadata: {metadata_blob}")
    
    # Upload preview
    preview_bytes = io.BytesIO()
    preview.save(preview_bytes, format='JPEG', quality=75, optimize=True)
    preview_bytes.seek(0)
    container_client.upload_blob(
        f"floorplans/{floorplan_id}/preview.jpg",
        preview_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="image/jpeg")
    )
    logger.info(f"Uploaded preview image")

    # Upload optimized base image (optional)
    if base_image_data is not None:
        try:
            base_filename = f"base-image.{base_image_format}"
            content_type = f"image/{base_image_format}" if base_image_format != "webp" else "image/webp"
            
            container_client.upload_blob(
                f"floorplans/{floorplan_id}/{base_filename}",
                base_image_data,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type)
            )
            size_mb = len(base_image_data) / (1024*1024)
            logger.info(f"Uploaded optimized base image: {base_filename} ({size_mb:.2f} MB, {base_image_format.upper()})")
        except Exception as be:
            logger.warning(f"Failed to upload base image: {be}")
    
    # Upload all tiles
    total_tiles = sum(len(tiles) for tiles in pyramid.values())
    uploaded = 0
    
    for zoom, tiles in pyramid.items():
        for x, y, tile_image in tiles:
            tile_bytes = io.BytesIO()
            # Use balanced compression (6) for good quality with smaller files
            tile_image.save(tile_bytes, format='PNG', compress_level=6)
            tile_bytes.seek(0)
            
            # Leaflet standard: {z}/{x}/{y}.png
            blob_path = f"floorplans/{floorplan_id}/tiles/{zoom}/{x}/{y}.png"
            container_client.upload_blob(
                blob_path,
                tile_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type="image/png")
            )
            
            uploaded += 1
            if uploaded % 10 == 0:
                logger.info(f"Upload progress: {uploaded}/{total_tiles} tiles")
    
    logger.info(f"✅ Successfully uploaded {total_tiles} tiles for {floorplan_id}")


def extract_floorplan_id(blob_name: str) -> str:
    """
    Extract floor plan ID from blob name.
    Example: floor-plans/myplan.pdf -> myplan
    """
    filename = blob_name.split('/')[-1]
    return filename.rsplit('.', 1)[0]


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Blocks Floorplan Tiler Service",
        "status": "running",
        "version": "2.0.0",
        "endpoint": "/api/process-floorplan"
    }


@app.get("/health")
async def health():
    """Kubernetes/Container Apps health probe"""
    return {"status": "healthy"}


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a processing job"""
    with jobs_lock:
        if job_id not in jobs_store:
            raise HTTPException(status_code=404, detail="Job not found")
        
        job = jobs_store[job_id]
        return {
            "job_id": job_id,
            "status": job["status"],
            "progress": job.get("progress", 0),
            "message": job.get("message", ""),
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "result": job.get("result")
        }


def update_job_progress(job_id: str, progress: int, message: str):
    """Helper to update job progress"""
    with jobs_lock:
        if job_id in jobs_store:
            jobs_store[job_id]["progress"] = progress
            jobs_store[job_id]["message"] = message
            jobs_store[job_id]["updated_at"] = datetime.utcnow().isoformat()


def process_floorplan_background(job_id: str, file_url: str):
    """Background task to process the floorplan"""
    try:
        # Update status to processing
        with jobs_lock:
            jobs_store[job_id]["status"] = JobStatus.PROCESSING
            jobs_store[job_id]["updated_at"] = datetime.utcnow().isoformat()
        
        # Call the synchronous processing logic
        result = process_floorplan_sync(file_url, job_id)
        
        # Mark as completed
        with jobs_lock:
            jobs_store[job_id]["status"] = JobStatus.COMPLETED
            jobs_store[job_id]["progress"] = 100
            jobs_store[job_id]["updated_at"] = datetime.utcnow().isoformat()
            jobs_store[job_id]["message"] = "Processing completed successfully"
            jobs_store[job_id]["result"] = result
            
    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}", exc_info=True)
        with jobs_lock:
            jobs_store[job_id]["status"] = JobStatus.FAILED
            jobs_store[job_id]["updated_at"] = datetime.utcnow().isoformat()
            jobs_store[job_id]["message"] = str(e)


@app.post("/api/process-floorplan")
async def process_floorplan(request: ProcessFloorplanRequest, background_tasks: BackgroundTasks):
    """
    Submit a PDF floorplan for processing (async - returns immediately).
    
    Args:
        request: ProcessFloorplanRequest with file_url
        
    Returns:
        JSON response with job_id for tracking progress
    """
    logger.info(f"Received floorplan processing request: {request.file_url}")
    
    # Generate job ID
    job_id = str(uuid.uuid4())
    
    # Create job record
    now = datetime.utcnow().isoformat()
    with jobs_lock:
        jobs_store[job_id] = {
            "job_id": job_id,
            "file_url": request.file_url,
            "status": JobStatus.QUEUED,
            "progress": 0,
            "message": "Job queued for processing",
            "created_at": now,
            "updated_at": now,
            "result": None
        }
    
    # Start background processing
    background_tasks.add_task(process_floorplan_background, job_id, request.file_url)
    
    logger.info(f"Job {job_id} queued for processing")
    
    return {
        "job_id": job_id,
        "status": JobStatus.QUEUED,
        "message": "Job queued for processing",
        "status_url": f"/api/status/{job_id}"
    }


def process_floorplan_sync(file_url: str, job_id: str):
    """
    Synchronous processing logic (moved from original async endpoint).
    Updates job progress throughout processing.
    
    Args:
        file_url: URL of the PDF to process
        job_id: Job ID for progress tracking
        
    Returns:
        Result dictionary with floorplan info
    """
    update_job_progress(job_id, 5, "Downloading PDF...")
    logger.info(f"Job {job_id}: Processing floorplan from URL: {file_url}")
    
    try:
        # Download the PDF from Azure Blob Storage or URL
        try:
            # Check if it's an Azure Blob Storage URL
            if 'blob.core.windows.net' in file_url:
                # Use Azure SDK to download from blob storage
                connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
                if not connection_string:
                    raise Exception("Storage connection string not configured")
                
                # Parse the blob URL to extract container and blob name
                from urllib.parse import urlparse
                parsed_url = urlparse(file_url)
                # URL format: https://<account>.blob.core.windows.net/<container>/<blob-path>
                path_parts = parsed_url.path.lstrip('/').split('/', 1)
                container_name = path_parts[0]
                blob_name = path_parts[1] if len(path_parts) > 1 else ''
                
                logger.info(f"Downloading from Azure Blob: container={container_name}, blob={blob_name}")
                
                blob_service = BlobServiceClient.from_connection_string(connection_string)
                blob_client = blob_service.get_blob_client(container_name, blob_name)
                file_content = blob_client.download_blob().readall()
                logger.info(f"Downloaded PDF from blob storage: {len(file_content)} bytes")
                update_job_progress(job_id, 10, "PDF downloaded, starting conversion...")
            else:
                # Download from external URL
                import urllib.request
                with urllib.request.urlopen(file_url) as response:
                    file_content = response.read()
                logger.info(f"Downloaded PDF from URL: {len(file_content)} bytes")
                update_job_progress(job_id, 10, "PDF downloaded, starting conversion...")
        except Exception as download_error:
            logger.error(f"Error downloading file: {str(download_error)}", exc_info=True)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to download file: {str(download_error)}"
            )
        
        # Extract filename from URL
        from urllib.parse import urlparse
        parsed_url = urlparse(file_url)
        floorplan_name = parsed_url.path.split('/')[-1]
        if not floorplan_name.lower().endswith('.pdf'):
            floorplan_name = 'floorplan.pdf'
        
        # Extract floorplan ID from filename (remove .pdf extension)
        floorplan_id = floorplan_name.rsplit('.', 1)[0]
        
        # Create a mock blob name for compatibility
        myblob_name = f"blocks/{floorplan_name}"
        
        # ============================================================
        # 🚀 PRODUCTION MODE - HIGH QUALITY TILING SETTINGS
        # ============================================================
        
        # 🎨 QUALITY SETTINGS (Configurable via environment variables):
        PDF_SCALE = float(os.environ.get('PDF_SCALE', '50.0'))  # 50.0=3600 DPI (ultra-extreme quality for deep zoom)
        MAX_DIMENSION = int(os.environ.get('MAX_DIMENSION', '30000'))  # 30K pixels max
        
        # 🗺️ TILING CONFIGURATION - DEEP ZOOM MODE:
        MAX_ZOOM_LIMIT = 12      # Maximum zoom levels allowed
        FORCED_MAX_Z_ENV = int(os.environ.get('FORCED_MAX_Z', '-1'))  # -1 = auto-calculate based on image size
        ZOOM_BOOST = int(os.environ.get('ZOOM_BOOST', '3'))  # Add extra zoom levels beyond native (for deep zoom with upscaling)
        TILE_SIZE_ENV = int(os.environ.get('TILE_SIZE', '512'))  # 512px tiles
        MIN_ZOOM_ENV = int(os.environ.get('MIN_ZOOM', '0'))  # Start from zoom level 0
        
        # ✅ Deep zoom with upscaling beyond native resolution
        # For PDF_SCALE=15: Native res at zoom ~6-7, upscales for 8-10
        # For PDF_SCALE=50: Native res at zoom ~8-9, upscales for 10-12
        # ============================================================
        
        # Check if the file is a PDF
        if not floorplan_name.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail="File must be a PDF"
            )

        # Guard: Only process PDFs uploaded at the container root to avoid re-processing
        try:
            container_and_rest = myblob_name.split('/', 1)
            relative_path = container_and_rest[1] if len(container_and_rest) > 1 else myblob_name
            if '/' in relative_path:
                logger.info(f"Ignoring nested PDF '{relative_path}' to prevent re-processing loop.")
                return JSONResponse(
                    content={"success": True, "message": "Skipped nested PDF to prevent re-processing"},
                    status_code=200
                )
        except Exception as _:
            pass
        
        logger.info(f"Processing PDF file: {myblob_name}")
        
        # Validate TILE_SIZE to supported values
        if TILE_SIZE_ENV not in (128, 256, 512, 1024):
            logger.warning(f"Unsupported TILE_SIZE={TILE_SIZE_ENV}; defaulting to 256")
            TILE_SIZE_ENV = 256

        logger.info(
            "Configuration overrides → "
            f"PDF_SCALE={PDF_SCALE}, MAX_DIMENSION={MAX_DIMENSION}, "
            f"MAX_ZOOM_LIMIT={MAX_ZOOM_LIMIT}, FORCED_MAX_Z={FORCED_MAX_Z_ENV}, "
            f"ZOOM_BOOST={ZOOM_BOOST}, TILE_SIZE={TILE_SIZE_ENV}, MIN_ZOOM={MIN_ZOOM_ENV}"
        )
        
        # 1. Convert PDF to PNG (single page expected)
        update_job_progress(job_id, 15, "Converting PDF to image...")
        images = pdf_to_images(file_content, scale=PDF_SCALE, max_dimension=MAX_DIMENSION)
        
        if len(images) == 0:
            raise Exception("No images generated from PDF")
        
        # Use first page (floor plans should be single page)
        floor_plan_image = images[0]
        logger.info(f"Floor plan dimensions (pre-trim): {floor_plan_image.width}x{floor_plan_image.height} pixels")
        update_job_progress(job_id, 20, "PDF converted, preparing image...")
        
        # Release extra images from memory immediately
        if len(images) > 1:
            for img in images[1:]:
                img.close()
            images = [floor_plan_image]

        # Optional: auto-trim white margins
        floor_plan_image = trim_whitespace(floor_plan_image, bg_color=(255, 255, 255), tolerance=10, padding=20)
        logger.info(f"Floor plan dimensions (post-trim): {floor_plan_image.width}x{floor_plan_image.height} pixels")
        
        # 2. Calculate optimal zoom levels for Leaflet tiles
        tile_size = TILE_SIZE_ENV
        
        # Calculate optimal max zoom based on image dimensions
        # Goal: Efficient tile distribution - zoom 0 should show full image in ~1-2 tiles
        if FORCED_MAX_Z_ENV == -1:
            # Smart calculation: Work backwards from zoom 0 constraint
            # At zoom 0, we want the entire image to fit in roughly 1-2 tiles per dimension
            # Simple CRS scaling: At zoom Z, scale = 2^(Z - max_zoom)
            # At zoom 0: scaled_size = original_size * 2^(0 - max_zoom) = original_size / (2^max_zoom)
            # We want: scaled_size ≈ tile_size (so it fits in ~1 tile at zoom 0)
            # So: original_size / (2^max_zoom) ≈ tile_size
            # Therefore: 2^max_zoom ≈ original_size / tile_size
            # max_zoom ≈ log2(original_size / tile_size)
            
            max_dim = max(floor_plan_image.width, floor_plan_image.height)
            
            # Calculate zoom where image naturally fits tile grid (no 1-tile waste)
            # This gives us the zoom level where the image is shown at native resolution
            base_zoom = math.ceil(math.log2(max_dim / tile_size))
            
            # Apply ZOOM_BOOST only if it doesn't create wasteful low-zoom levels
            # Check if adding boost would make zoom 0 show image < tile_size (1 tile only)
            min_dimension_at_zoom_0 = min(floor_plan_image.width, floor_plan_image.height) / (2 ** (base_zoom + ZOOM_BOOST))
            
            if min_dimension_at_zoom_0 < tile_size / 2:
                # Would create 1-tile zoom levels - reduce boost
                adjusted_boost = max(0, math.floor(math.log2(min(floor_plan_image.width, floor_plan_image.height) / (tile_size / 2))))
                max_zoom = max(0, min(base_zoom + adjusted_boost, MAX_ZOOM_LIMIT))
                logger.info(
                    f"🎯 Auto-calculated max zoom: {max_zoom} "
                    f"(base: {base_zoom}, boost adjusted: {adjusted_boost} to avoid 1-tile waste, "
                    f"image {floor_plan_image.width}x{floor_plan_image.height})"
                )
            else:
                # Boost is safe - won't create 1-tile levels
                max_zoom = max(0, min(base_zoom + ZOOM_BOOST, MAX_ZOOM_LIMIT))
                logger.info(
                    f"🎯 Auto-calculated max zoom: {max_zoom} "
                    f"(base: {base_zoom}, boost: +{ZOOM_BOOST}, "
                    f"image {floor_plan_image.width}x{floor_plan_image.height})"
                )
        else:
            # Use forced max zoom from environment
            max_zoom = max(0, min(FORCED_MAX_Z_ENV, MAX_ZOOM_LIMIT))
            logger.info(f"Using forced max zoom: {max_zoom}")
        
        min_zoom = max(0, min(MIN_ZOOM_ENV, max_zoom))
        total_levels = (max_zoom - min_zoom + 1)
        logger.info(f"Using Leaflet zoom levels: {min_zoom}-{max_zoom} (total {total_levels})")

        # Log native tile density at highest zoom
        native_tiles_x = math.ceil(floor_plan_image.width / (tile_size * 2**(max_zoom)))
        native_tiles_y = math.ceil(floor_plan_image.height / (tile_size * 2**(max_zoom)))
        native_total_tiles = native_tiles_x * native_tiles_y
        logger.info(
            "Max-zoom native tile grid: "
            f"{native_tiles_x}x{native_tiles_y} (total {native_total_tiles}) at {floor_plan_image.width}x{floor_plan_image.height}px"
        )
        
        # 3. Generate tile pyramid using Simple CRS
        logger.info("🗺️ Generating Simple CRS tile pyramid with high quality...")
        update_job_progress(job_id, 30, f"Generating {total_levels} zoom levels of tiles...")
        
        zoom_levels = list(range(min_zoom, max_zoom + 1))
        floorplan_tiler = SimpleFloorplanTiler(tile_size=tile_size)
        pyramid = floorplan_tiler.tile_image(floor_plan_image, zoom_levels)
        total_tiles = sum(len(tiles) for tiles in pyramid.values())
        logger.info(f"Generated {total_tiles} high-quality tiles across {len(pyramid)} zoom levels")
        update_job_progress(job_id, 60, f"Generated {total_tiles} tiles, uploading to storage...")
        
        # 4. Generate preview image
        logger.info("Generating preview image...")
        preview = generate_preview(floor_plan_image, max_width=800)
        
        # Skip base image to save memory - tiles are sufficient
        logger.info("⚠️ Skipping base image save to conserve memory for large floorplans")
        
        # 5. Create metadata
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
            "dpi": PDF_SCALE * 72
        }
        logger.info(f"Created metadata for floor plan: {floorplan_id}")
        
        # 6. Upload to blob storage
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            raise HTTPException(
                status_code=500,
                detail="Storage connection string not configured"
            )
        
        logger.info("Uploading tiles and assets to blob storage...")
        upload_tiles_to_blob(
            pyramid=pyramid,
            preview=preview,
            metadata=metadata,
            floorplan_id=floorplan_id,
            original_blob_name=myblob_name,
            connection_string=connection_string,
            container="blocks",
            base_image=None,
            base_image_data=None,
            base_image_format="png"
        )
        update_job_progress(job_id, 90, f"Uploaded {total_tiles} tiles to storage...")
        
        # Release memory
        preview.close()
        for zoom_tiles in pyramid.values():
            for _, _, tile_img in zoom_tiles:
                tile_img.close()
        pyramid.clear()
        logger.info("✅ Cleaned up image memory after upload")

        # 7. Archive the original PDF
        blob_service = BlobServiceClient.from_connection_string(connection_string)
        source_container = "blocks"

        try:
            dest_blob_name = f"floorplans/{floorplan_id}/{floorplan_id}.pdf"
            dest_client = blob_service.get_blob_client(source_container, dest_blob_name)
            content_settings = ContentSettings(content_type="application/pdf")
            dest_client.upload_blob(file_content, overwrite=True, content_settings=content_settings)
            logger.info(f"Archived original PDF at: {dest_blob_name}")
        except Exception as copy_err:
            logger.warning(f"Could not store archived PDF copy: {str(copy_err)}")
        
        update_job_progress(job_id, 95, "Finalizing floor plan processing...")
        
        logger.info(f"🚀 Successfully created tiled floor plan: {floorplan_id}")
        logger.info(f"   📐 Dimensions: {floor_plan_image.width}x{floor_plan_image.height}px")
        logger.info(f"   🎨 Quality: {PDF_SCALE * 72:.0f} DPI (PDF_SCALE={PDF_SCALE})")
        logger.info(f"   ️ Zoom levels: {total_levels} ({min_zoom}-{max_zoom})")
        logger.info(f"   🏗️ Total tiles: {total_tiles}")
        
        # Return success response
        return {
            "success": True,
            "floorplan_id": floorplan_id,
            "dimensions": {
                "width": floor_plan_image.width,
                "height": floor_plan_image.height
            },
            "quality": {
                "dpi": int(PDF_SCALE * 72)
            },
            "tiles": {
                "total": total_tiles,
                "zoom_levels": total_levels,
                "min_zoom": min_zoom,
                "max_zoom": max_zoom,
                "tile_size": tile_size
            },
            "urls": {
                "metadata": f"https://blocksplayground.blob.core.windows.net/blocks/floorplans/{floorplan_id}/metadata.json",
                "preview": f"https://blocksplayground.blob.core.windows.net/blocks/floorplans/{floorplan_id}/preview.png",
                "tiles": f"https://blocksplayground.blob.core.windows.net/blocks/floorplans/{floorplan_id}/tiles/{{z}}/{{x}}/{{y}}.png"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )


if __name__ == "__main__":
    # For local development
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
