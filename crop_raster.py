import rasterio
from rasterio.windows import Window

input_path = "data/development/rasters/dev_004.tif"
output_path = "data/fast_test.tif"

with rasterio.open(input_path) as src:
    window = Window(0, 0, 2000, 2000)
    kwargs = src.meta.copy()
    kwargs.update({
        'height': window.height,
        'width': window.width,
        'transform': rasterio.windows.transform(window, src.transform)
    })
    
    with rasterio.open(output_path, 'w', **kwargs) as dst:
        dst.write(src.read(window=window))
