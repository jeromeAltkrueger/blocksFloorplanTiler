# Image Tiling Logic and Storage

A focused guide on the core logic for splitting images into web map tiles and storing them properly.

## Table of Contents

1. [Core Tiling Process](#core-tiling-process)
2. [Mathematical Implementation](#mathematical-implementation)
3. [Tile Generation Logic](#tile-generation-logic)
4. [Storage Format and Structure](#storage-format-and-structure)
5. [Complete Implementation](#complete-implementation)

## Core Tiling Process

### Input Requirements

**For Floorplan/Indoor Maps:**

**You must provide:**
- **Source Image**: Any floorplan/indoor map image
- **Bounds**: Custom coordinate system (CAN BE SAME FOR ALL IMAGES!)
- **Zoom Levels**: Which zoom levels to generate (YOU CHOOSE - e.g., 10-16)

**✅ For Floorplans - You CAN reuse the same bounds:**

```python
# Standard bounds for ALL your floorplan images
standard_bounds = {
    'north': 1.0,   # Top of your coordinate system
    'south': 0.0,   # Bottom of your coordinate system  
    'east': 1.0,    # Right edge
    'west': 0.0     # Left edge
}

# Use for Building A floorplan
# Use for Building B floorplan  
# Use for Building C floorplan
# All use the same bounds = 0,0 to 1,1 coordinate system
```

**What's automatic:**
- Number of tiles needed (calculated from bounds + zoom levels)
- Tile coordinates (calculated from your custom bounds)
- Image cropping and resizing (handled automatically)
- Directory structure creation

**What you decide once (and reuse for ALL floorplans):**
- Standard bounds for your floorplan coordinate system  
- Standard zoom levels for consistent detail across all floorplans

**✅ Recommended Standard Zoom Levels for Floorplans:**

```python
# Use these same zoom levels for ALL floorplans
STANDARD_ZOOM_LEVELS = [10, 12, 14, 16, 18]

# 10-12: Overview level (see entire floorplan)
# 14-16: Room detail level  
# 18+: Fine detail level (furniture, fixtures)
```

### ❌ **Cannot Reuse Geographic Bounds**

Each image needs its own bounds based on what it actually shows:

```python
# Image 1: Aerial photo of New York Central Park
bounds_nyc = {
    'north': 40.7831, 'south': 40.7489,
    'east': -73.9441, 'west': -73.9927
}

# Image 2: Aerial photo of London Hyde Park  
bounds_london = {
    'north': 51.5133, 'south': 51.5017,
    'east': -0.1573, 'west': -0.1759
}

# ❌ WRONG: Using NYC bounds for London image = tiles in wrong location!
# ✅ CORRECT: Each image gets bounds matching its real-world location
```

### Process Overview
1. **Load Image**: Read the source image into memory
2. **Calculate Tile Coverage**: Determine which tiles are needed for each zoom level
3. **Generate Tiles**: Extract and resize image portions for each tile
4. **Save Tiles**: Store tiles in the standard folder structure

## Mathematical Implementation

### Web Mercator Tile Math

```python
import math
from typing import Tuple, Dict

class TileMath:
    def __init__(self, tile_size: int = 256):
        self.tile_size = tile_size
        self.origin_shift = 2 * math.pi * 6378137 / 2.0  # Earth circumference / 2
    
    def lat_lon_to_meters(self, lat: float, lon: float) -> Tuple[float, float]:
        """Convert lat/lon to Web Mercator meters (EPSG:3857)"""
        mx = lon * self.origin_shift / 180.0
        my = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
        my = my * self.origin_shift / 180.0
        return mx, my
    
    def meters_to_pixels(self, mx: float, my: float, zoom: int) -> Tuple[float, float]:
        """Convert Web Mercator meters to pixel coordinates at zoom level"""
        resolution = self.origin_shift * 2 / self.tile_size / (2 ** zoom)
        px = (mx + self.origin_shift) / resolution
        py = (my + self.origin_shift) / resolution
        return px, py
    
    def pixels_to_tile(self, px: float, py: float) -> Tuple[int, int]:
        """Convert pixel coordinates to tile coordinates"""
        tx = int(math.floor(px / self.tile_size))
        ty = int(math.floor(py / self.tile_size))
        return tx, ty
    
    def lat_lon_to_tile(self, lat: float, lon: float, zoom: int) -> Tuple[int, int]:
        """Convert lat/lon directly to tile coordinates"""
        mx, my = self.lat_lon_to_meters(lat, lon)
        px, py = self.meters_to_pixels(mx, my, zoom)
        return self.pixels_to_tile(px, py)
    
    def tile_bounds_meters(self, tx: int, ty: int, zoom: int) -> Dict[str, float]:
        """Get the Web Mercator bounds of a tile"""
        resolution = self.origin_shift * 2 / self.tile_size / (2 ** zoom)
        minx = tx * self.tile_size * resolution - self.origin_shift
        maxx = (tx + 1) * self.tile_size * resolution - self.origin_shift
        miny = ty * self.tile_size * resolution - self.origin_shift
        maxy = (ty + 1) * self.tile_size * resolution - self.origin_shift
        return {'minx': minx, 'miny': miny, 'maxx': maxx, 'maxy': maxy}
    
    def google_tile(self, tx: int, ty: int, zoom: int) -> Tuple[int, int]:
        """Convert TMS coordinates to Google/XYZ (flip Y axis)"""
        return tx, (2 ** zoom) - 1 - ty
```

## Tile Generation Logic

### Core Tiler Class

```python
from PIL import Image
import os
from typing import Dict, List

class ImageTiler:
    def __init__(self):
        self.tile_math = TileMath()
    
    def tile_image(self, 
                   image_path: str,
                   bounds: Dict[str, float],  # {'north': lat, 'south': lat, 'east': lon, 'west': lon}
                   zoom_levels: List[int],
                   output_dir: str) -> Dict[str, int]:
        """
        Main function to tile an image
        
        Returns: Dictionary with tile counts per zoom level
        """
        # Load the source image
        with Image.open(image_path) as img:
            img = img.convert('RGBA')
            img_width, img_height = img.size
        
        # Calculate image bounds in Web Mercator meters
        west_mx, north_my = self.tile_math.lat_lon_to_meters(bounds['north'], bounds['west'])
        east_mx, south_my = self.tile_math.lat_lon_to_meters(bounds['south'], bounds['east'])
        
        image_bounds = {
            'minx': west_mx, 'maxx': east_mx,
            'miny': south_my, 'maxy': north_my
        }
        
        # Generate tiles for each zoom level
        tile_counts = {}
        for zoom in zoom_levels:
            count = self._generate_zoom_level(img, image_bounds, zoom, output_dir)
            tile_counts[zoom] = count
            print(f"Generated {count} tiles for zoom level {zoom}")
        
        return tile_counts
    
    def _generate_zoom_level(self, 
                           source_img: Image.Image,
                           image_bounds: Dict[str, float],
                           zoom: int,
                           output_dir: str) -> int:
        """Generate all tiles for a specific zoom level"""
        
        # Find tile range that covers the image
        min_tx, max_ty = self.tile_math.meters_to_pixels(image_bounds['minx'], image_bounds['maxy'], zoom)
        max_tx, min_ty = self.tile_math.meters_to_pixels(image_bounds['maxx'], image_bounds['miny'], zoom)
        
        min_tile_x, max_tile_y = self.tile_math.pixels_to_tile(min_tx, max_ty)
        max_tile_x, min_tile_y = self.tile_math.pixels_to_tile(max_tx, min_ty)
        
        tile_count = 0
        
        # Create zoom directory
        zoom_dir = os.path.join(output_dir, str(zoom))
        os.makedirs(zoom_dir, exist_ok=True)
        
        # Generate each tile
        for ty in range(min_tile_y, max_tile_y + 1):
            for tx in range(min_tile_x, max_tile_x + 1):
                tile_img = self._create_tile(source_img, image_bounds, tx, ty, zoom)
                if tile_img:
                    # Convert to Google/XYZ coordinates for storage
                    gx, gy = self.tile_math.google_tile(tx, ty, zoom)
                    self._save_tile(tile_img, gx, gy, zoom, output_dir)
                    tile_count += 1
        
        return tile_count
    
    def _create_tile(self, 
                    source_img: Image.Image,
                    image_bounds: Dict[str, float],
                    tx: int, ty: int, zoom: int) -> Image.Image:
        """Create a single tile from the source image"""
        
        # Get tile bounds in Web Mercator meters
        tile_bounds = self.tile_math.tile_bounds_meters(tx, ty, zoom)
        
        # Check if tile intersects with image
        if (tile_bounds['maxx'] < image_bounds['minx'] or
            tile_bounds['minx'] > image_bounds['maxx'] or
            tile_bounds['maxy'] < image_bounds['miny'] or
            tile_bounds['miny'] > image_bounds['maxy']):
            return None
        
        # Calculate intersection area
        intersect_minx = max(tile_bounds['minx'], image_bounds['minx'])
        intersect_miny = max(tile_bounds['miny'], image_bounds['miny'])
        intersect_maxx = min(tile_bounds['maxx'], image_bounds['maxx'])
        intersect_maxy = min(tile_bounds['maxy'], image_bounds['maxy'])
        
        img_width, img_height = source_img.size
        
        # Calculate source pixels in original image
        img_meter_width = image_bounds['maxx'] - image_bounds['minx']
        img_meter_height = image_bounds['maxy'] - image_bounds['miny']
        
        # Map intersection to source image pixels
        src_left = int((intersect_minx - image_bounds['minx']) / img_meter_width * img_width)
        src_right = int((intersect_maxx - image_bounds['minx']) / img_meter_width * img_width)
        src_top = int((image_bounds['maxy'] - intersect_maxy) / img_meter_height * img_height)
        src_bottom = int((image_bounds['maxy'] - intersect_miny) / img_meter_height * img_height)
        
        # Clamp to image bounds
        src_left = max(0, min(src_left, img_width))
        src_right = max(0, min(src_right, img_width))
        src_top = max(0, min(src_top, img_height))
        src_bottom = max(0, min(src_bottom, img_height))
        
        if src_right <= src_left or src_bottom <= src_top:
            return None
        
        # Extract portion from source image
        source_crop = source_img.crop((src_left, src_top, src_right, src_bottom))
        
        # Create 256x256 tile
        tile_img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
        
        # Calculate where to place the cropped image in the tile
        tile_meter_width = tile_bounds['maxx'] - tile_bounds['minx']
        tile_meter_height = tile_bounds['maxy'] - tile_bounds['miny']
        
        dst_left = int((intersect_minx - tile_bounds['minx']) / tile_meter_width * 256)
        dst_right = int((intersect_maxx - tile_bounds['minx']) / tile_meter_width * 256)
        dst_top = int((tile_bounds['maxy'] - intersect_maxy) / tile_meter_height * 256)
        dst_bottom = int((tile_bounds['maxy'] - intersect_miny) / tile_meter_height * 256)
        
        # Resize and paste
        dst_width = dst_right - dst_left
        dst_height = dst_bottom - dst_top
        
        if dst_width > 0 and dst_height > 0:
            resized_crop = source_crop.resize((dst_width, dst_height), Image.Resampling.LANCZOS)
            tile_img.paste(resized_crop, (dst_left, dst_top))
        
        return tile_img
    
    def _save_tile(self, tile_img: Image.Image, x: int, y: int, zoom: int, output_dir: str):
        """Save tile to disk in standard format"""
        # Create directory structure: output_dir/z/x/y.png
        tile_dir = os.path.join(output_dir, str(zoom), str(x))
        os.makedirs(tile_dir, exist_ok=True)
        
        tile_path = os.path.join(tile_dir, f"{y}.png")
        tile_img.save(tile_path, 'PNG', optimize=True)
```

## Storage Format and Structure

### Standard Tile Directory Structure

```
tiles/
├── metadata.json                 # Image info and bounds
├── 10/                          # Zoom level 10
│   ├── 512/                     # X coordinate
│   │   ├── 256.png             # Y coordinate
│   │   ├── 257.png
│   │   └── 258.png
│   ├── 513/
│   │   ├── 256.png
│   │   └── 257.png
├── 11/                          # Zoom level 11
│   ├── 1024/
│   │   ├── 512.png
│   │   └── 513.png
└── 12/                          # Higher zoom levels...
    └── 2048/
        └── 1024.png
```

### Metadata Storage

```python
import json
from datetime import datetime

def save_metadata(output_dir: str, 
                 image_path: str,
                 bounds: Dict[str, float],
                 zoom_levels: List[int],
                 tile_counts: Dict[str, int]):
    """Save metadata about the tiled image"""
    
    metadata = {
        "source_image": os.path.basename(image_path),
        "created_at": datetime.now().isoformat(),
        "bounds": bounds,
        "zoom_levels": zoom_levels,
        "tile_counts": tile_counts,
        "total_tiles": sum(tile_counts.values()),
        "tile_format": "png",
        "tile_size": 256,
        "coordinate_system": "Google/XYZ (Web Mercator)"
    }
    
    metadata_path = os.path.join(output_dir, "metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, indent=2, fp=f)
```

### URL Template for Web Use

After tiling, your tiles can be accessed with this URL pattern:
```
http://your-server.com/tiles/{z}/{x}/{y}.png
```

For local files:
```
file:///path/to/tiles/{z}/{x}/{y}.png
```

## Complete Implementation

### Usage Example

```python
def tile_my_image():
    """Complete example of tiling an image"""
    
    # Initialize the tiler
    tiler = ImageTiler()
    
    # Define your floorplan image and bounds
    image_path = "building_a_floor_1.png"
    
    # Standard bounds for ALL floorplans (reuse this!)
    bounds = {
        'north': 1.0,   # Top of floorplan
        'south': 0.0,   # Bottom of floorplan
        'east': 1.0,    # Right edge
        'west': 0.0     # Left edge
    }
    
    # Standard zoom levels - USE SAME FOR ALL FLOORPLANS
    zoom_levels = [10, 12, 14, 16, 18]  # Consistent across all floorplans
    
    # FLOORPLAN ZOOM GUIDE:
    # 10-12: Full floorplan overview
    # 14-16: Room/area detail level
    # 18+: Fine detail (furniture, fixtures)
    
    # Output directory
    output_dir = "tiles/my_image"
    
    # Generate tiles
    print(f"Tiling image: {image_path}")
    print(f"Bounds: {bounds}")
    print(f"Zoom levels: {zoom_levels}")
    
    tile_counts = tiler.tile_image(
        image_path=image_path,
        bounds=bounds,
        zoom_levels=zoom_levels,
        output_dir=output_dir
    )
    
    # Save metadata
    save_metadata(output_dir, image_path, bounds, zoom_levels, tile_counts)
    
    print(f"Tiling complete! Generated {sum(tile_counts.values())} total tiles")
    print(f"Tiles saved to: {output_dir}")
    print(f"URL template: {output_dir}/{{z}}/{{x}}/{{y}}.png")

def tile_multiple_floorplans():
    """Example: Tile multiple floorplans with same bounds"""
    
    # CONSTANTS - Same for ALL floorplans
    STANDARD_BOUNDS = {'north': 1.0, 'south': 0.0, 'east': 1.0, 'west': 0.0}
    STANDARD_ZOOM_LEVELS = [10, 12, 14, 16, 18]
    
    floorplans = [
        "building_a_floor_1.png",
        "building_a_floor_2.png", 
        "building_b_floor_1.png",
        "office_layout.png"
    ]
    
    tiler = ImageTiler()
    
    for floorplan in floorplans:
        print(f"Processing: {floorplan}")
        output_dir = f"tiles/{floorplan.replace('.png', '')}"
        
        # Same bounds AND zoom levels for every floorplan!
        tile_counts = tiler.tile_image(
            image_path=floorplan,
            bounds=STANDARD_BOUNDS,      # Same for all!
            zoom_levels=STANDARD_ZOOM_LEVELS,  # Same for all!
            output_dir=output_dir
        )
        
        print(f"  → Generated {sum(tile_counts.values())} tiles\n")

if __name__ == "__main__":
    tile_my_image()
```

### Dependencies

**Only one library needed:**

```txt
Pillow==10.1.0
```

**Why Pillow?**
- Load/save images (PNG, JPEG, TIFF, etc.)
- Crop and resize image portions
- Handle transparency (RGBA)

**Everything else is pure Python:**
- All the math (trigonometry, coordinate transforms)
- File system operations (creating directories)
- JSON handling for metadata

### Installation and Run

```bash
# Install only Pillow
pip install Pillow

# Run the tiler (pure Python + Pillow)
python image_tiler.py
```

## What Gets Calculated Automatically

### Based on Your Image Bounds & Zoom Levels:

```python
# Example: If your image covers a small area...
bounds = {
    'north': 40.7831, 'south': 40.7489,  # ~3.4km tall
    'east': -73.9441, 'west': -73.9927    # ~4.2km wide  
}

# At zoom 12: ~1-4 tiles
# At zoom 15: ~64-256 tiles  
# At zoom 18: ~4,096-16,384 tiles

# The system calculates:
# 1. Which tile coordinates (x,y) are needed
# 2. How many tiles total per zoom level
# 3. What portion of your image goes in each tile
# 4. Automatic cropping and resizing
```

### Automatic Calculations:

1. **Tile Count**: Based on image size vs tile size at each zoom
2. **Tile Coordinates**: Which (x,y) tiles intersect your image
3. **Image Cropping**: What part of your image goes in each tile  
4. **Coordinate Transforms**: Lat/lon → meters → pixels → tiles
5. **File Paths**: Creates `z/x/y.png` structure automatically

### What You Control:

- **Zoom Range**: `[10, 15]` vs `[12, 18]` = different tile counts
- **Image Bounds**: Must match your image's real-world location
- **Output Quality**: Higher zooms = more detail = more files

## Key Points

1. **Coordinate System**: Uses Google/XYZ tile coordinates (Y=0 at top)
2. **File Format**: PNG files for transparency support
3. **Directory Structure**: Standard `z/x/y.png` format
4. **Tile Size**: 256×256 pixels (web standard)
5. **Projection**: Web Mercator (EPSG:3857)
6. **Optimization**: Only generates tiles that intersect with the image

This implementation gives you the core tiling logic and proper storage structure for web map compatibility.