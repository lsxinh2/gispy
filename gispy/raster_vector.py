from osgeo import gdal, ogr, osr
import numpy as np
from scipy import stats
import math
import struct
import os
import raster
import vector


def bboxToOffsets(bbox, geot):
    col1 = int((bbox[0] - geot[0]) / geot[1])
    col2 = int((bbox[1] - geot[0]) / geot[1]) + 1
    row1 = int((bbox[3] - geot[3]) / geot[5])
    row2 = int((bbox[2] - geot[3]) / geot[5]) + 1
    return [row1, row2, col1, col2]


def clipByFeature(inputdir, outputdir, rasterfiles, shapefile, fieldname, nodata=-9999, xres=None, yres=None):
    """
    Clip multiple rasters by features in a shapefile. Creates a new directory for each feature and saves clipped rasters in the directory

    Note:
        All input rasters and shapefiles should have the same spatial reference

    Args:
        inputdir: directory where rasters to be clipped are located
        outputdir: directory where a new directory for each clipped raster will be created
        rasterfiles: list of raster file names and extensions to be clipped. e.g. ['raster1.tif', 'raster2.tif]
        shapefile: shapefile containing features to clip with
        fieldname: name of field to select feature with
        nodata: nodata value (default: -9999)
        xres: x resolution of output raster (default: None), with default resolution is taken from the input rater
        yres: y resolution of output rater (defaul: None), with default resolution is taken from the input rater

    Returns:
        None

    """
    fieldValues, fids = vector.getFieldValues(shapefile, fieldname)
    fieldValues_unique = list(set(fieldValues)) #get unique field values (otherwise the same operation may be done twice)
    for value in fieldValues_unique:
        dirvalue = outputdir + "/" + str(value)
        if not os.path.isdir(dirvalue):
            os.mkdir(dirvalue)
        for raster in rasterfiles:
            infile = inputdir + "/" + str(raster)
            if os.path.exists(infile):
                clipRasterWithPolygon(infile, shapefile, dirvalue + "/" + str(raster), nodata=nodata, xres=xres, yres=yres,
                                      fieldValue=value, field=fieldname)
    return None


def clipRasterWithPolygon(rasterpath, polygonpath, outputpath, nodata=-9999, xres=None, yres=None, field=None, fieldValue=None):
    """

    Args:
        rasterpath: raster to clip
        polygonpath: shapefile containing features to clip with
        outputpath: path of output clipped raster
        nodata: nodata value (default: -9999)
        xres: x resolution of output raster (default: None, resolution of input raster)
        yres: y resolution of output raster (default: None, resolution of input raster)
        field: name of shapefile field to select features and name directories
        fieldValue: list of unique values for input field

    Returns:

    """
    if xres is None or yres is None: xres, yres = raster.getXYResolution(rasterpath)
    if field is not None and fieldValue is not None: wexp = str(field) + " = \'" + str(fieldValue) + "\'"
    else: wexp = None

    warpOptions = gdal.WarpOptions(format='GTiff', cutlineDSName=polygonpath, cropToCutline=True, cutlineWhere=wexp, xRes=xres, yRes=abs(yres), dstNodata=nodata)
    gdal.WarpOptions()
    gdal.Warp(outputpath, rasterpath, options=warpOptions)
    return None


def polygonToRaster(rasterpath, vectorpath, fieldname, rows, cols, geot, prj=None, drivername='GTiff', allcells=False, nodata=-9999, datatype = gdal.GDT_Float32, islayer=False):
    """
    Convert polygon shapefile to raster dataset.

    Args:
        rasterpath: Path of raster to be created.
        vectorpath: Path of polygon shapefile to rasterize.
        fieldname: Name of shapefile field to use as values in new raster.
        rows: Number of rows in new raster.
        cols: Number of columns in new raster.
        geot: Affine geotransform of new raster.
        prj: Spatial reference of new raster.
        drivername: Name of GDAL driver to use to create raster (default: 'GTiff')
        allcells: If all cells intersected by polygons should be rasterized, or just when polygon includes cell center (defaul: False).
        nodata: No data value.
        datatype: GDAL datatype of new raster (default: gdal.GDT_Float32).
        islayer (bool): True if vector path is an OGRLayer (default: False)

    Returns:

    """
    if islayer:
        lyr = vectorpath
    else:
        inds = ogr.Open(vectorpath)
        lyr = inds.GetLayer()
    driver = gdal.GetDriverByName(drivername)
    outds = driver.Create(rasterpath, cols, rows, 1, datatype)
    outds.SetProjection(prj)
    outds.SetGeoTransform(geot)
    band = outds.GetRasterBand(1).ReadAsArray()
    band.fill(nodata)
    outds.GetRasterBand(1).WriteArray(band)
    outds.GetRasterBand(1).SetNoDataValue(nodata)

    ALL_TOUCHED = 'FALSE'
    if allcells: ALL_TOUCHED = 'TRUE'

    if vector.fieldExists(lyr, fieldname):
        status = gdal.RasterizeLayer(outds, [1], lyr, options=['ALL_TOUCHED='+ALL_TOUCHED, 'ATTRIBUTE='+fieldname, 'NODATA='+str(nodata)])
        if status is not 0:
            print "Rasterize not successful"
    else:
        print "Rasterize field does not exist"

    if inds: inds = None
    outds = None
    return None


def rasterValueAtPoints(pointshapefile, rasterpath, fieldname, datatype=ogr.OFTReal, idxfield=None):
    """
    Get the value of a raster at point locations.

    Args:
        pointshapefile: Path to point shapefile.
        rasterpath: Path to raster dataset.
        fieldname: Name of field to create and write raster values.
        datatype: OGR datatype of created field (default: ogr.OFTReal)
        idxfield: Shapefile field containing band number to use on multipband rasters (default: None, get value from band 1)

    Returns:

    """
    ras = raster.openGDALRaster(rasterpath)
    geot = ras.GetGeoTransform()
    shp = vector.openOGRDataSource(pointshapefile, 1)
    lyr = shp.GetLayer()
    if lyr.GetGeomType() is not ogr.wkbPoint:
        print "incorrect geometry type, should be points", lyr.GetGeomType()
        return None
    vector.createFields(lyr, [fieldname], datatype)
    feat = lyr.GetNextFeature()
    while feat:
        nband = 1
        if idxfield is not None:
            nband = feat.GetField(idxfield)
        geom = feat.GetGeometryRef()
        row, col = raster.getCellAddressOfPoint(geom.GetX(), geom.GetY(), geot)
        if nband <= 0 or nband > ras.RasterCount:
            value = -9999.0
        else:
            value = struct.unpack('f'*1, ras.GetRasterBand(int(nband)).ReadRaster(xoff=col, yoff=row, xsize=1, ysize=1,
                                                                      buf_xsize=1, buf_ysize=1,
                                                                      buf_type=gdal.GDT_Float32))[0]
        feat.SetField(fieldname, value)
        lyr.SetFeature(feat)
        feat = lyr.GetNextFeature()
    lyr = None
    shp.Destroy()

def rasterZonesFromVector_delta(vectorpath, rasterpath, outputpath, deltavalue=10000.0, deltatype='percent', minvalue = 0.0):
    np.set_printoptions(suppress=True)
    rasterds = raster.openGDALRaster(rasterpath)
    vectords = vector.openOGRDataSource(vectorpath)
    print "data opened"
    lyr = vectords.GetLayer()
    geot = rasterds.GetGeoTransform()
    nodata = rasterds.GetRasterBand(1).GetNoDataValue()
    outds = raster.createGDALRaster(outputpath, rasterds.RasterYSize, rasterds.RasterXSize, geot=geot,
                                    datatype=gdal.GDT_Int32)
    print "datacreated"
    #outds.GetRasterBand(1).Fill(-1)
    print "filled"
    outds.GetRasterBand(1).SetNoDataValue(-1)
    outds.SetProjection(rasterds.GetProjection())
    outofbounds = []
    feat = lyr.GetNextFeature()
    iter = 0
    print "starting loop"
    while feat:
        id = feat.GetFID()
        tmpds = vector.createOGRDataSource('temp', 'Memory')
        tmplyr = tmpds.CreateLayer('polygons', None, ogr.wkbPolygon)
        tmplyr.CreateFeature(feat.Clone())
        offsets = bboxToOffsets(feat.GetGeometryRef().GetEnvelope(), geot)
        for i in range(0, len(offsets)):
            if offsets[i] < 0:
                offsets[i] = 0
        if not any(x < 0 for x in offsets):
            array = rasterds.GetRasterBand(1).ReadAsArray(offsets[2], offsets[0], (offsets[3] - offsets[2]),
                                                          (offsets[1] - offsets[0]))
            outarray = outds.GetRasterBand(1).ReadAsArray(offsets[2], offsets[0], (offsets[3] - offsets[2]),
                                                          (offsets[1] - offsets[0]))
            newgeot = raster.getOffsetGeot(offsets[0], offsets[2], geot)
            tmpras = raster.createGDALRaster('', offsets[1] - offsets[0], offsets[3] - offsets[2],
                                             datatype=gdal.GDT_Byte,
                                             drivername='MEM', geot=newgeot)
            gdal.RasterizeLayer(tmpras, [1], tmplyr, burn_values=[1])
            tmparray = tmpras.ReadAsArray()
            featarray = np.ma.MaskedArray(array,
                                              mask=np.logical_or(array == nodata, np.logical_not(tmparray)))
            featmean = np.ma.mean(featarray)

            if featmean != nodata:
                median = np.ma.median(featarray)
                diff = (abs(featarray - median) / median) * 100.0
                # print "array"
                # print np.around(array)
                # print "diff"
                # print np.around(diff)
                maskarray = np.ma.MaskedArray(array,
                                              mask=np.logical_or(np.ma.getmask(featarray),
                                                                 np.logical_or(diff > deltavalue, array < minvalue)))
                maskarray.set_fill_value(-1)
                maskarray = maskarray.filled()
                maskarray = np.where(maskarray>=0, id, np.where(outarray>=0, outarray, maskarray))
                # print "feat array"
                # print tmparray
                # print "result"
                # print maskarray
                outds.GetRasterBand(1).WriteArray(maskarray, offsets[2], offsets[0])

        else:
            print "out of bounds", feat.GetFID()
            outofbounds.append(feat.GetFID())
        tmpras = None
        tmpds = None
        iter += 1
        if (iter % 10000 == 0):
            print "iter", iter, "of", lyr.GetFeatureCount()
        feat = lyr.GetNextFeature()
    #outds = None
    print "done"
    return None

def setFeatureStats(fid, min=None, max=None, sd=None, mean=None, median=None, sum=None, count=None, majority=None, deltamed=None):
    featstats = {
        'min': min,
        'mean': mean,
        'median': median,
        'max': max,
        'sd': sd,
        'sum': sum,
        'count': count,
        'majority': majority,
        'fid': fid,
        'deltamed': deltamed
    }
    return featstats


def zonalStatistics(vectorpath, rasterpath, write=['min', 'max', 'sd', 'mean'], prepend=None, idxfield=None):
    rasterds = raster.openGDALRaster(rasterpath)
    vectords = vector.openOGRDataSource(vectorpath)
    lyr = vectords.GetLayer()
    geot = rasterds.GetGeoTransform()
    array = rasterds.ReadAsArray()
    nodata = rasterds.GetRasterBand(1).GetNoDataValue()
    zstats=[]
    feat = lyr.GetNextFeature()
    while feat:
        tmpds = vector.createOGRDataSource('temp', 'Memory')
        tmplyr = tmpds.CreateLayer('polygons', None, ogr.wkbPolygon)
        tmplyr.CreateFeature(feat.Clone())
        offsets = bboxToOffsets(feat.GetGeometryRef().GetEnvelope(), geot)
        newgeot= raster.getOffsetGeot(offsets[0], offsets[2], geot)
        tmpras = raster.createGDALRaster('', offsets[1]-offsets[0], offsets[3]-offsets[2], datatype=gdal.GDT_Byte, drivername='MEM', geot=newgeot)
        gdal.RasterizeLayer(tmpras, [1], tmplyr, burn_values=[1])
        tmparray = tmpras.ReadAsArray()
        maskarray = np.ma.MaskedArray(array[offsets[0]:offsets[1], offsets[2]:offsets[3]],
                                      mask=np.logical_or(array[offsets[0]:offsets[1], offsets[2]:offsets[3]]==nodata, np.logical_not(tmparray)))
        featstats = {
            'min' : float(maskarray.min()),
            'mean': float(maskarray.mean()),
            'max': float(maskarray.max()),
            'sd': float(maskarray.std()),
            'sum': float(maskarray.sum()),
            'count': float(maskarray.count()),
            'fid': float(feat.GetFID())
        }
        zstats.append(featstats)
        tmpras = None
        tmpds = None
        feat = lyr.GetNextFeature()
    return zstats


def zonalStatisticsDelta(vectorpath, rasterpath, deltapath, deltavalue, deltatype='percent', minvalue=0.0):
    """
    Zonal statistics using a second raster layer to exclude values from statistic calculations. Currently,
    This is implemented as follows. For each zone represented in vectorpath, the median of deltapath is identified.
    Cells from deltapath where the absolute value of ((median - deltapath)/median)*100 is greater than delta value are
    excluded from statistical calculations.

    Args:
        vectorpath: Vector zones
        rasterpath: Raster to calculate statistics from
        deltapath: Raster to exclude cells for statistic calculation
        deltavalue: Threshold for exclusion from statistic calculations
        deltatype: Type of theshold to use. Currently, only percent is available.

    Returns:

    """
    rasterds = raster.openGDALRaster(rasterpath)
    deltads = raster.openGDALRaster(deltapath)
    vectords = vector.openOGRDataSource(vectorpath)
    lyr = vectords.GetLayer()
    geot = rasterds.GetGeoTransform()
    nodata = rasterds.GetRasterBand(1).GetNoDataValue()
    zstats = []
    outofbounds = []
    feat = lyr.GetNextFeature()
    iter = 0
    while feat:
        tmpds = vector.createOGRDataSource('temp', 'Memory')
        tmplyr = tmpds.CreateLayer('polygons', None, ogr.wkbPolygon)
        tmplyr.CreateFeature(feat.Clone())
        offsets = bboxToOffsets(feat.GetGeometryRef().GetEnvelope(), geot)
        for i in range(0, len(offsets)):
            if offsets[i] < 0:
                offsets[i] = 0
        if not any(x < 0 for x in offsets):
            array = rasterds.GetRasterBand(1).ReadAsArray(offsets[2], offsets[0], (offsets[3]-offsets[2]),
                                                          (offsets[1]-offsets[0]))
            deltaarray = deltads.GetRasterBand(1).ReadAsArray(offsets[2], offsets[0], (offsets[3]-offsets[2]),
                                                          (offsets[1]-offsets[0]))
            newgeot = raster.getOffsetGeot(offsets[0], offsets[2], geot)
            tmpras = raster.createGDALRaster('', offsets[1] - offsets[0], offsets[3] - offsets[2], datatype=gdal.GDT_Byte,
                                             drivername='MEM', geot=newgeot)
            gdal.RasterizeLayer(tmpras, [1], tmplyr, burn_values=[1])
            tmparray = tmpras.ReadAsArray()
            testmaskarray = np.ma.MaskedArray(array,
                                               mask=np.logical_or(array == nodata, np.logical_not(tmparray)))
            testmean = np.ma.mean(testmaskarray)

            if testmean != nodata:
                deltamaskarray = np.ma.MaskedArray(deltaarray,
                                                   mask=np.logical_or(array == nodata, np.logical_not(tmparray)))
                median = np.ma.median(deltamaskarray)
                diff = (abs(deltamaskarray - median) / median) * 100.0
                maskarray = np.ma.MaskedArray(array, mask=np.logical_or(np.ma.getmask(deltamaskarray),
                                                                        np.logical_or(diff > deltavalue,
                                                                                      array < minvalue)))

                zstats.append(setFeatureStats(feat.GetFID(), min=float(maskarray.min()), mean=float(maskarray.mean()),
                                             max=float(maskarray.max()), sum=float(maskarray.sum()), sd=float(maskarray.std()),
                                             median=float(np.ma.median(maskarray)), majority=float(stats.mode(maskarray, axis=None)[0][0]),
                                              deltamed=float((median*30*30)/1000000), count=maskarray.count()))
            else:
                zstats.append(setFeatureStats(feat.GetFID()))

        else:
            print "out of bounds", feat.GetFID()
            zstats.append(setFeatureStats(feat.GetFID()))
            outofbounds.append(feat.GetFID())
        tmpras = None
        tmpds = None
        iter+=1
        # if (iter % 1000 == 0):
        #     print "iter", iter, "of", lyr.GetFeatureCount()
        feat = lyr.GetNextFeature()
    return zstats

def zonalStatistics_rasterZones(rasterzones, rasterpath, indentifier="fid"):
    zones = raster.getRasterBandAsArray(rasterzones, 1)
    rasterds = raster.openGDALRaster(rasterpath)
    rastervals = rasterds.GetRasterBand(1).ReadAsArray()
    nodata = rasterds.GetRasterBand(1).GetNoDataValue()
    uvals = np.unique(zones)
    zstats = []
    iter = 0
    for uval in uvals:
        if uval >= 0:
            vals = rastervals[np.where(zones == uval)]
            vals = vals[vals != nodata]
            zstats.append(setFeatureStats(uval, max=float(vals.max()), min=float(vals.min()),
                                          mean=float(vals.max()), sd=float(vals.std()),
                                          median=float(np.median(vals)),
                                          majority=float(stats.mode(vals, axis=None)[0][0]),
                                          count=vals.size))
        iter += 1
        if (iter % 10000 == 0):
            print "iter", iter, "of", len(uvals)
    return zstats
