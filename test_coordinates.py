"""
Test coordinate transformation with user's actual metadata
This demonstrates the CORRECT coordinate system for Leaflet CRS.Simple
"""

# Real metadata from user's floorplan (ID: 120021)
metadata = {
    "floorplan_id": "120021",
    "source_image": {
        "width": 23891,
        "height": 12558
    },
    "tile_size": 512,
    "max_zoom": 10,
    "min_zoom": 0,
    # NOTE: These bounds are WRONG in the metadata (they're in pixels, not Leaflet space)
    "bounds": [[0, 0], [12558, 23891]],
    "coordinate_system": "Simple CRS (L.CRS.Simple)"
}

def calculate_correct_leaflet_bounds(metadata):
    """Calculate the CORRECT Leaflet CRS.Simple bounds"""
    width = metadata["source_image"]["width"]
    height = metadata["source_image"]["height"]
    max_zoom = metadata["max_zoom"]
    tile_size = metadata["tile_size"]

    # At max zoom: leafletCoord = pixelCoord / tileSize
    scale_factor = tile_size * (2 ** (max_zoom - max_zoom))  # = tileSize

    leaflet_width = width / scale_factor
    leaflet_height = height / scale_factor

    return {
        "lon_min": 0,
        "lat_min": 0,
        "lon_max": leaflet_width,
        "lat_max": leaflet_height,
        "bounds": [[0, 0], [leaflet_height, leaflet_width]]
    }

def leaflet_to_pdf_coords(leaflet_coords, leaflet_bounds, pdf_size):
    """Transform from Leaflet space to PDF pixel space"""
    x_leaflet, y_leaflet = leaflet_coords
    pdf_width, pdf_height = pdf_size

    lon_min = leaflet_bounds["lon_min"]
    lat_min = leaflet_bounds["lat_min"]
    lon_max = leaflet_bounds["lon_max"]
    lat_max = leaflet_bounds["lat_max"]

    # First, convert to normalized coordinates (0-1 range)
    x_norm = (x_leaflet - lon_min) / (lon_max - lon_min) if lon_max != lon_min else 0
    y_norm = (y_leaflet - lat_min) / (lat_max - lat_min) if lat_max != lat_min else 0

    # Then scale to PDF dimensions
    x_pdf = x_norm * pdf_width
    y_pdf = y_norm * pdf_height

    return x_pdf, y_pdf

print("=" * 80)
print("LEAFLET CRS.SIMPLE COORDINATE SYSTEM TEST")
print("=" * 80)
print()

# Calculate correct Leaflet bounds
leaflet_bounds = calculate_correct_leaflet_bounds(metadata)

print("📊 METADATA ANALYSIS")
print("-" * 80)
print(f"Floorplan ID: {metadata['floorplan_id']}")
print(f"Source image: {metadata['source_image']['width']} x {metadata['source_image']['height']} pixels")
print(f"Max zoom: {metadata['max_zoom']}")
print(f"Tile size: {metadata['tile_size']}")
print()

print("🔧 COORDINATE SPACE CALCULATION")
print("-" * 80)
print(f"Formula: leafletCoord = pixelCoord / (tileSize * 2^(maxZoom - maxZoom))")
print(f"         leafletCoord = pixelCoord / {metadata['tile_size']}")
print()
print(f"Leaflet width:  {metadata['source_image']['width']} / {metadata['tile_size']} = {leaflet_bounds['lon_max']:.2f}")
print(f"Leaflet height: {metadata['source_image']['height']} / {metadata['tile_size']} = {leaflet_bounds['lat_max']:.2f}")
print()

print("✅ CORRECT LEAFLET BOUNDS")
print("-" * 80)
print(f"Bounds: [[0, 0], [{leaflet_bounds['lat_max']:.2f}, {leaflet_bounds['lon_max']:.2f}]]")
print(f"Longitude (X) range: 0 to {leaflet_bounds['lon_max']:.2f}")
print(f"Latitude (Y) range:  0 to {leaflet_bounds['lat_max']:.2f}")
print()

print("❌ WRONG BOUNDS IN METADATA")
print("-" * 80)
print(f"Metadata has: {metadata['bounds']}")
print(f"These are PIXEL coordinates, NOT Leaflet coordinate space!")
print(f"This is a bug in the tile generation metadata.")
print()

print("=" * 80)
print("YOUR INPUT COORDINATES ANALYSIS")
print("=" * 80)
print()

# User's problematic input
user_coords = [
    [4.84375, -11.71875],
    [4.84375, -0.78125],
    [14.5625, -0.78125],
    [14.5625, -11.71875]
]

print("🔴 Your Input Coordinates:")
print("-" * 80)
for i, (x, y) in enumerate(user_coords):
    print(f"Point {i}: [x={x:10.5f}, y={y:10.5f}]")

print()
print("❌ PROBLEM DETECTED:")
print("-" * 80)
print(f"✗ X range: {min(c[0] for c in user_coords):.2f} to {max(c[0] for c in user_coords):.2f}")
print(f"  Expected: 0 to {leaflet_bounds['lon_max']:.2f}")
print()
print(f"✗ Y range: {min(c[1] for c in user_coords):.2f} to {max(c[1] for c in user_coords):.2f}")
print(f"  Expected: 0 to {leaflet_bounds['lat_max']:.2f}")
print()
print(f"✗ NEGATIVE Y VALUES!")
print(f"✗ Values are way too small!")
print()

print("=" * 80)
print("🎯 SOLUTION: HOW TO GET CORRECT COORDINATES")
print("=" * 80)
print()

print("1️⃣  Initialize your Leaflet map with CORRECT bounds:")
print("-" * 80)
print(f"""
// Fetch metadata first
const metadata = await fetch('metadata.json').then(r => r.json());

// Calculate correct Leaflet bounds
const tileSize = metadata.tile_size;
const maxZoom = metadata.max_zoom;
const scaleFactor = tileSize * Math.pow(2, maxZoom - maxZoom); // = tileSize

const leafletWidth = metadata.source_image.width / scaleFactor;
const leafletHeight = metadata.source_image.height / scaleFactor;

// CORRECT bounds for Leaflet CRS.Simple
const bounds = [[0, 0], [leafletHeight, leafletWidth]];
// For your floorplan: [[0, 0], [{leaflet_bounds['lat_max']:.2f}, {leaflet_bounds['lon_max']:.2f}]]

const map = L.map('map', {{
    crs: L.CRS.Simple,
    maxBounds: bounds,
    maxBoundsViscosity: 1.0,
    minZoom: metadata.min_zoom,
    maxZoom: metadata.max_zoom + 3
}});

// Set view to center
const center = [leafletHeight / 2, leafletWidth / 2];
map.setView(center, metadata.max_zoom);

// Add tile layer
L.tileLayer(tileUrl, {{
    tileSize: tileSize,
    minNativeZoom: metadata.min_zoom,
    maxNativeZoom: metadata.max_zoom,
    bounds: bounds,
    noWrap: true
}}).addTo(map);
""")

print()
print("2️⃣  When you draw on the map, coordinates will be in correct range:")
print("-" * 80)
print(f"Expected X (longitude): 0 to {leaflet_bounds['lon_max']:.2f}")
print(f"Expected Y (latitude):  0 to {leaflet_bounds['lat_max']:.2f}")
print()

print("3️⃣  Example of CORRECT coordinates for a small rectangle:")
print("-" * 80)
# Create a small example rectangle (10% of image, centered)
example_coords = [
    [leaflet_bounds['lon_max'] * 0.4, leaflet_bounds['lat_max'] * 0.4],
    [leaflet_bounds['lon_max'] * 0.4, leaflet_bounds['lat_max'] * 0.6],
    [leaflet_bounds['lon_max'] * 0.6, leaflet_bounds['lat_max'] * 0.6],
    [leaflet_bounds['lon_max'] * 0.6, leaflet_bounds['lat_max'] * 0.4],
    [leaflet_bounds['lon_max'] * 0.4, leaflet_bounds['lat_max'] * 0.4]
]

print("// Example GeoJSON for annotation API:")
print("""{
  "type": "Feature",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[""")
for coord in example_coords:
    print(f"      [{coord[0]:.2f}, {coord[1]:.2f}],")
print("""    ]]
  },
  "properties": {
    "type": "rectangle"
  }
}""")

print()
print("=" * 80)
print("📋 SUMMARY")
print("=" * 80)
print()
print("✅ Your PDF annotation code is now FIXED and will work correctly!")
print("❌ Your Leaflet map is NOT using the correct coordinate system")
print("🔧 Follow the solution above to fix your Leaflet map")
print("📝 Use the test viewer (viewer_annotation_test.html) to get correct coords")
print()
print("=" * 80)
