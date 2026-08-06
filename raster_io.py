"""
Raster I/O with bounded memory using rasterio windowed reads.
=============================================================
Handles diverse GeoTIFF inputs: varying band counts, dtypes,
nodata masks, CRS, and affine transforms.
"""

import logging
from dataclasses import dataclass
from typing import Generator, Optional, Tuple

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.transform import Affine
from pyproj import Transformer, CRS

logger = logging.getLogger(__name__)


@dataclass
class RasterMeta:
    """Metadata extracted from a raster file."""
    width: int
    height: int
    crs: CRS
    transform: Affine
    dtype: str
    band_count: int
    nodata: Optional[float]
    color_interp: list


@dataclass
class TileInfo:
    """Information about a single tile extracted from the raster."""
    # The RGB image data as float32 [H, W, 3] in [0, 1]
    image: np.ndarray
    # Validity mask: True where data is valid
    valid_mask: np.ndarray
    # Window offset in full-raster pixel coordinates
    col_off: int
    row_off: int
    # Actual (un-padded) window size before padding to tile_size
    src_width: int
    src_height: int
    # Scale factors used to resize to model input
    scale_x: float
    scale_y: float
    # Padding applied
    pad_right: int
    pad_bottom: int


def get_raster_meta(raster_path: str) -> RasterMeta:
    """Read metadata from a raster without loading pixel data."""
    with rasterio.open(raster_path) as ds:
        meta = RasterMeta(
            width=ds.width,
            height=ds.height,
            crs=CRS.from_user_input(ds.crs),
            transform=ds.transform,
            dtype=str(ds.dtypes[0]),
            band_count=ds.count,
            nodata=ds.nodata,
            color_interp=[ci.name for ci in ds.colorinterp],
        )
        logger.info(f"  Raster: {ds.width}x{ds.height}, {ds.count} bands, "
                     f"dtype={ds.dtypes[0]}, CRS={ds.crs}, nodata={ds.nodata}")
        logger.info(f"  Color interpretation: {meta.color_interp}")
        logger.info(f"  Transform: {ds.transform}")
        return meta


def _normalize_to_rgb_float32(
    data: np.ndarray,
    color_interp: list,
    nodata: Optional[float],
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert raw band data to RGB float32 in [0, 1] and a validity mask.

    Parameters
    ----------
    data : np.ndarray
        Raw pixel data, shape [bands, H, W].
    color_interp : list
        List of color interpretation strings per band.
    nodata : float or None
        Nodata value if present.

    Returns
    -------
    rgb : np.ndarray [H, W, 3] float32 in [0, 1]
    valid_mask : np.ndarray [H, W] bool
    """
    bands, h, w = data.shape

    # Build validity mask
    if nodata is not None:
        valid_mask = np.all(data != nodata, axis=0)
    else:
        valid_mask = np.ones((h, w), dtype=bool)

    # Also mask fully-zero pixels across all bands (common in orthomosaics for no-data areas)
    all_zero = np.all(data == 0, axis=0)
    valid_mask = valid_mask & ~all_zero

    # Handle alpha channel if present
    interp_lower = [ci.lower() for ci in color_interp]
    if "alpha" in interp_lower:
        alpha_idx = interp_lower.index("alpha")
        alpha_band = data[alpha_idx].astype(np.float32)
        alpha_max = alpha_band.max()
        if alpha_max > 0:
            valid_mask = valid_mask & (alpha_band > 0)

    # Extract RGB bands
    if bands >= 3:
        # Try to find RGB by color interpretation
        if "red" in interp_lower and "green" in interp_lower and "blue" in interp_lower:
            r_idx = interp_lower.index("red")
            g_idx = interp_lower.index("green")
            b_idx = interp_lower.index("blue")
            rgb = np.stack([data[r_idx], data[g_idx], data[b_idx]], axis=-1)
        else:
            # Assume first three bands are RGB
            rgb = np.stack([data[0], data[1], data[2]], axis=-1)
    elif bands == 1:
        # Grayscale -> replicate to 3 channels
        rgb = np.stack([data[0], data[0], data[0]], axis=-1)
    else:
        # 2 bands -> use first two + zeros
        rgb = np.stack([data[0], data[1], np.zeros_like(data[0])], axis=-1)

    # Convert to float32 [0, 1]
    rgb = rgb.astype(np.float32)
    dt = rgb.dtype
    info = np.finfo(dt) if np.issubdtype(dt, np.floating) else None

    # Determine normalization range
    raw_max = rgb.max()
    if raw_max > 1.0:
        if raw_max <= 255.0:
            rgb /= 255.0
        elif raw_max <= 65535.0:
            rgb /= 65535.0
        else:
            rgb /= raw_max
    
    # Clamp to [0, 1]
    np.clip(rgb, 0.0, 1.0, out=rgb)

    # Zero out invalid pixels
    rgb[~valid_mask] = 0.0

    return rgb, valid_mask


def generate_tiles(
    raster_path: str,
    tile_size: int = 640,
    overlap: int = 128,
) -> Generator[TileInfo, None, None]:
    """
    Generate tiles from a raster using windowed reads for bounded memory.

    Yields TileInfo objects containing the RGB image ready for the model,
    validity mask, and coordinate transformation parameters.

    Parameters
    ----------
    raster_path : str
        Path to the GeoTIFF raster.
    tile_size : int
        Size of the model input (assumes square).
    overlap : int
        Overlap in pixels between adjacent tiles.
    """
    meta = get_raster_meta(raster_path)
    stride = tile_size - overlap

    with rasterio.open(raster_path) as ds:
        img_h, img_w = ds.height, ds.width
        color_interp = [ci.name for ci in ds.colorinterp]

        # Calculate number of tiles in each dimension
        # Ensure we cover the entire image including edges
        n_cols = max(1, (img_w - overlap + stride - 1) // stride)
        n_rows = max(1, (img_h - overlap + stride - 1) // stride)

        total_tiles = n_cols * n_rows
        logger.info(f"  Tiling: {n_cols}x{n_rows} = {total_tiles} tiles "
                     f"(stride={stride}, overlap={overlap})")

        tile_idx = 0
        for row_i in range(n_rows):
            for col_i in range(n_cols):
                # Calculate window origin
                col_off = col_i * stride
                row_off = row_i * stride

                # Clamp to ensure we don't go past the image edge
                # For the last tile in a row/column, shift back so we
                # capture the edge completely
                if col_off + tile_size > img_w:
                    col_off = max(0, img_w - tile_size)
                if row_off + tile_size > img_h:
                    row_off = max(0, img_h - tile_size)

                # Actual read dimensions (may be smaller than tile_size for tiny images)
                read_w = min(tile_size, img_w - col_off)
                read_h = min(tile_size, img_h - row_off)

                # Read window from raster (bounded memory — only this window)
                window = Window(col_off, row_off, read_w, read_h)
                # Read all bands for this window
                data = ds.read(window=window)  # [bands, read_h, read_w]

                # Normalize to RGB float32 [0, 1]
                rgb, valid_mask = _normalize_to_rgb_float32(
                    data, color_interp, meta.nodata
                )

                # Free raw data immediately
                del data

                # Pad to tile_size if necessary (for edge tiles of small images)
                pad_bottom = tile_size - read_h
                pad_right = tile_size - read_w

                if pad_bottom > 0 or pad_right > 0:
                    rgb = np.pad(
                        rgb,
                        ((0, pad_bottom), (0, pad_right), (0, 0)),
                        mode="constant",
                        constant_values=0.5,  # neutral gray padding
                    )
                    valid_mask = np.pad(
                        valid_mask,
                        ((0, pad_bottom), (0, pad_right)),
                        mode="constant",
                        constant_values=False,
                    )

                tile_idx += 1
                if tile_idx % 100 == 0 or tile_idx == total_tiles:
                    logger.info(f"    Tile {tile_idx}/{total_tiles}")

                yield TileInfo(
                    image=rgb,
                    valid_mask=valid_mask,
                    col_off=col_off,
                    row_off=row_off,
                    src_width=read_w,
                    src_height=read_h,
                    scale_x=1.0,  # tile_size == read window when image >= tile_size
                    scale_y=1.0,
                    pad_right=pad_right,
                    pad_bottom=pad_bottom,
                )


def pixel_to_wgs84(
    pixel_x: float,
    pixel_y: float,
    raster_path: str,
) -> Tuple[float, float]:
    """
    Convert full-raster pixel coordinates to WGS84 (longitude, latitude).

    Parameters
    ----------
    pixel_x : float
        Column coordinate in the full raster.
    pixel_y : float
        Row coordinate in the full raster.
    raster_path : str
        Path to the GeoTIFF raster.

    Returns
    -------
    (longitude, latitude) in WGS84.
    """
    with rasterio.open(raster_path) as ds:
        # Convert pixel to CRS coordinates using the affine transform
        # rasterio xy() expects (row, col) and returns (x, y) in the raster's CRS
        crs_x, crs_y = ds.xy(pixel_y, pixel_x)

        raster_crs = ds.crs

    # If already WGS84, return directly
    if CRS.from_user_input(raster_crs).to_epsg() == 4326:
        return crs_x, crs_y

    # Otherwise, reproject to WGS84
    transformer = Transformer.from_crs(
        CRS.from_user_input(raster_crs),
        CRS.from_epsg(4326),
        always_xy=True,
    )
    lon, lat = transformer.transform(crs_x, crs_y)
    return lon, lat


def batch_pixel_to_wgs84(
    pixels: list,
    raster_path: str,
) -> list:
    """
    Convert a batch of full-raster pixel coordinates to WGS84.

    Parameters
    ----------
    pixels : list of (pixel_x, pixel_y)
    raster_path : str

    Returns
    -------
    list of (longitude, latitude)
    """
    if not pixels:
        return []

    with rasterio.open(raster_path) as ds:
        transform = ds.transform
        raster_crs = CRS.from_user_input(ds.crs)

    # Convert all pixel coords to CRS coords using the affine transform
    # The affine transform maps pixel (col, row) -> (x, y) in CRS
    # rasterio convention: transform * (col, row) gives (x, y)
    crs_coords = []
    for px, py in pixels:
        crs_x, crs_y = transform * (px, py)
        crs_coords.append((crs_x, crs_y))

    # Reproject to WGS84 if needed
    if raster_crs.to_epsg() == 4326:
        return crs_coords

    transformer = Transformer.from_crs(
        raster_crs,
        CRS.from_epsg(4326),
        always_xy=True,
    )
    wgs84_coords = []
    for cx, cy in crs_coords:
        lon, lat = transformer.transform(cx, cy)
        wgs84_coords.append((lon, lat))

    return wgs84_coords


def get_raster_bounds(raster_path: str) -> Tuple[int, int]:
    """Return (width, height) of the raster."""
    with rasterio.open(raster_path) as ds:
        return ds.width, ds.height
