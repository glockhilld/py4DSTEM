# Functions for finding Bragg disks.
#
# Using a vacuum probe as a template - i.e. a convolution kernel - a cross correlation (or phase or
# hybrid correlation) is taken between each DP and the template, and the positions and intensities
# of all local correlation maxima are used to identify the Bragg disks. Erroneous peaks are filtered
# out with several types of threshold. Detected Bragg disks are generally stored in PointLists (when
# run on only selected DPs) or PointListArrays (when run on a full DataCube).

import numpy as np
from scipy.ndimage.filters import gaussian_filter
from time import time

from ...file.datastructure import PointList, PointListArray
from ..utils import get_cross_correlation_fk, get_maxima_2D, print_progress_bar, upsampled_correlation

def find_Bragg_disks_single_DP_FK(DP, probe_kernel_FT,
                                  corrPower = 1,
                                  sigma = 2,
                                  edgeBoundary = 20,
                                  minRelativeIntensity = 0.005,
                                  minPeakSpacing = 60,
                                  maxNumPeaks = 70,
                                  subpixel = 'poly',
                                  upsample_factor = 4,
                                  return_cc = False,
                                  peaks = None):
    """
    Finds the Bragg disks in DP by cross, hybrid, or phase correlation with probe_kernel_FT.

    After taking the cross/hybrid/phase correlation, a gaussian smoothing is applied
    with standard deviation sigma, and all local maxima are found. Detected peaks within
    edgeBoundary pixels of the diffraction plane edges are then discarded. Next, peaks with
    intensities less than minRelativeIntensity of the brightest peak in the correaltion are
    discarded. Then peaks which are within a distance of minPeakSpacing of their nearest neighbor
    peak are found, and in each such pair the peak with the lesser correlation intensities is
    removed. Finally, if the number of peaks remaining exceeds maxNumPeaks, only the maxNumPeaks
    peaks with the highest correlation intensity are retained.

    IMPORTANT NOTE: the argument probe_kernel_FT is related to the probe kernels generated by
    functions like get_probe_kernel() by:

            probe_kernel_FT = np.conj(np.fft.fft2(probe_kernel))

    if this function is simply passed a probe kernel, the results will not be meaningful! To run
    on a single DP while passing the real space probe kernel as an argument, use
    find_Bragg_disks_single_DP().

    Accepts:
        DP                   (ndarray) a diffraction pattern
        probe_kernel_FT      (ndarray) the vacuum probe template, in Fourier space. Related to the
                             real space probe kernel by probe_kernel_FT = F(probe_kernel)*, where F
                             indicates a Fourier Transform and * indicates complex conjugation.
        corrPower            (float between 0 and 1, inclusive) the cross correlation power. A
                             value of 1 corresponds to a cross correaltion, and 0 corresponds to a
                             phase correlation, with intermediate values giving various hybrids.
        sigma                (float) the standard deviation for the gaussian smoothing applied to
                             the cross correlation
        edgeBoundary         (int) minimum acceptable distance from the DP edge, in pixels
        minRelativeIntensity (float) the minimum acceptable correlation peak intensity, relative to
                             the intensity of the brightest peak
        minPeakSpacing       (float) the minimum acceptable spacing between detected peaks
        maxNumPeaks          (int) the maximum number of peaks to return
        subpixel             (str)          'none': no subpixel fitting
                                    default 'poly': polynomial interpolation of correlogram peaks
                                                    (fairly fast but not very accurate)
                                            'multicorr': uses the multicorr algorithm with 
                                                        DFT upsampling
        upsample_factor      (int) upsampling factor for subpixel fitting (only used when subpixel='multicorr')
        return_cc            (bool) if True, return the cross correlation
        peaks                (PointList) For internal use.
                             If peaks is None, the PointList of peak positions is created here.
                             If peaks is not None, it is the PointList that detected peaks are added
                             to, and must have the appropriate coords ('qx','qy','intensity').

    Returns:
        peaks                (PointList) the Bragg peak positions and correlation intensities
    """
    assert subpixel in [ 'none', 'poly', 'multicorr' ], "Unrecognized subpixel option {}, subpixel must be 'none', 'poly', or 'multicorr'".format(subpixel)

    if subpixel == 'none':
        cc = get_cross_correlation_fk(DP, probe_kernel_FT, corrPower)
        cc = np.maximum(cc,0)
        maxima_x,maxima_y,maxima_int = get_maxima_2D(cc, sigma=sigma,
                                                     edgeBoundary=edgeBoundary,
                                                     minRelativeIntensity=minRelativeIntensity,
                                                     minSpacing=minPeakSpacing,
                                                     maxNumPeaks=maxNumPeaks,
                                                     subpixel=False)
    elif subpixel == 'poly':
        cc = get_cross_correlation_fk(DP, probe_kernel_FT, corrPower)
        cc = np.maximum(cc,0)
        maxima_x,maxima_y,maxima_int = get_maxima_2D(cc, sigma=sigma,
                                                     edgeBoundary=edgeBoundary,
                                                     minRelativeIntensity=minRelativeIntensity,
                                                     minSpacing=minPeakSpacing,
                                                     maxNumPeaks=maxNumPeaks,
                                                     subpixel=True)
    else:
        # Multicorr subpixel:
        m = np.fft.fft2(DP) * probe_kernel_FT
        ccc = np.abs(m)**(corrPower) * np.exp(1j*np.angle(m))

        cc = np.maximum(np.real(np.fft.ifft2(ccc)),0)

        maxima_x,maxima_y,maxima_int = get_maxima_2D(cc, sigma=sigma,
                                                     edgeBoundary=edgeBoundary,
                                                     minRelativeIntensity=minRelativeIntensity,
                                                     minSpacing=minPeakSpacing,
                                                     maxNumPeaks=maxNumPeaks,
                                                     subpixel=True)

        # Use the DFT upsample to refine the detected peaks (but not the intensity)
        for ipeak in range(len(maxima_x)):
            xyShift = np.array((maxima_x[ipeak],maxima_y[ipeak]))
            # we actually have to lose some precision and go down to half-pixel
            # accuracy. this could also be done by a single upsampling at factor 2
            # instead of get_maxima_2D.
            xyShift[0] = np.round(xyShift[0] * 2) / 2
            xyShift[1] = np.round(xyShift[1] * 2) / 2

            subShift = upsampled_correlation(ccc,upsample_factor,xyShift)
            maxima_x[ipeak]=subShift[0]
            maxima_y[ipeak]=subShift[1]

    # Make peaks PointList
    if peaks is None:
        coords = [('qx',float),('qy',float),('intensity',float)]
        peaks = PointList(coordinates=coords)
    else:
        assert(isinstance(peaks,PointList))
    peaks.add_tuple_of_nparrays((maxima_x,maxima_y,maxima_int))

    if return_cc:
        return peaks, gaussian_filter(cc,sigma)
    else:
        return peaks


def find_Bragg_disks_single_DP(DP, probe_kernel,
                               corrPower = 1,
                               sigma = 2,
                               edgeBoundary = 20,
                               minRelativeIntensity = 0.005,
                               minPeakSpacing = 60,
                               maxNumPeaks = 70,
                               subpixel = 'poly',
                               upsample_factor = 4,
                               return_cc = False):
    """
    Identical to find_Bragg_disks_single_DP_FK, accept that this function accepts a probe_kernel in
    real space, rather than Fourier space. For more info, see the find_Bragg_disks_single_DP_FK
    documentation.

    Accepts:
        DP                   (ndarray) a diffraction pattern
        probe_kernel         (ndarray) the vacuum probe template, in real space.
        corrPower            (float between 0 and 1, inclusive) the cross correlation power. A
                             value of 1 corresponds to a cross correaltion, and 0 corresponds to a
                             phase correlation, with intermediate values giving various hybrids.
        sigma                (float) the standard deviation for the gaussian smoothing applied to
                             the cross correlation
        edgeBoundary         (int) minimum acceptable distance from the DP edge, in pixels
        minRelativeIntensity (float) the minimum acceptable correlation peak intensity, relative to
                             the intensity of the brightest peak
        minPeakSpacing       (float) the minimum acceptable spacing between detected peaks
        maxNumPeaks          (int) the maximum number of peaks to return
        subpixel             (str)          'none': no subpixel fitting
                                    default 'poly': polynomial interpolation of correlogram peaks
                                                    (fairly fast but not very accurate)
                                            'multicorr': uses the multicorr algorithm with 
                                                        DFT upsampling
        upsample_factor      (int) upsampling factor for subpixel fitting (only used when subpixel='multicorr')
        return_cc            (bool) if True, return the cross correlation

    Returns:
        peaks                (PointList) the Bragg peak positions and correlation intensities

    """
    probe_kernel_FT = np.conj(np.fft.fft2(probe_kernel))
    return find_Bragg_disks_single_DP_FK(DP, probe_kernel_FT,
                                         corrPower = corrPower,
                                         sigma = sigma,
                                         edgeBoundary = edgeBoundary,
                                         minRelativeIntensity = minRelativeIntensity,
                                         minPeakSpacing = minPeakSpacing,
                                         maxNumPeaks = maxNumPeaks,
                                         subpixel = subpixel,
                                         upsample_factor = upsample_factor,
                                         return_cc = return_cc)


def find_Bragg_disks_selected(datacube, probe, Rx, Ry,
                              corrPower = 1,
                              sigma = 2,
                              edgeBoundary = 20,
                              minRelativeIntensity = 0.005,
                              minPeakSpacing = 60,
                              maxNumPeaks = 70,
                              subpixel = 'poly',
                              upsample_factor = 4):
    """
    Finds the Bragg disks in the diffraction patterns of datacube at scan positions (Rx,Ry) by
    cross, hybrid, or phase correlation with probe.

    Accepts:
        DP                   (ndarray) a diffraction pattern
        probe                (ndarray) the vacuum probe template, in real space.
        Rx                   (int or tuple/list of ints) scan position x-coords of DPs of interest
        Ry                   (int or tuple/list of ints) scan position y-coords of DPs of interest
        corrPower            (float between 0 and 1, inclusive) the cross correlation power. A
                             value of 1 corresponds to a cross correaltion, and 0 corresponds to a
                             phase correlation, with intermediate values giving various hybrids.
        sigma                (float) the standard deviation for the gaussian smoothing applied to
                             the cross correlation
        edgeBoundary         (int) minimum acceptable distance from the DP edge, in pixels
        minRelativeIntensity (float) the minimum acceptable correlation peak intensity, relative to
                             the intensity of the brightest peak
        minPeakSpacing       (float) the minimum acceptable spacing between detected peaks
        maxNumPeaks          (int) the maximum number of peaks to return
        subpixel             (str)          'none': no subpixel fitting
                                    default 'poly': polynomial interpolation of correlogram peaks
                                                    (fairly fast but not very accurate)
                                            'multicorr': uses the multicorr algorithm with 
                                                        DFT upsampling
        upsample_factor      (int) upsampling factor for subpixel fitting (only used when subpixel='multicorr')

    Returns:
        peaks                (n-tuple of PointLists, n=len(Rx)) the Bragg peak positions and
                             correlation intensities at each scan position (Rx,Ry)
    """
    assert(len(Rx)==len(Ry))
    peaks = []

    # Get probe kernel in Fourier space
    probe_kernel_FT = np.conj(np.fft.fft2(probe))

    # Loop over selected diffraction patterns
    t0 = time()
    for i in range(len(Rx)):
        DP = datacube.data[Rx[i],Ry[i],:,:]
        peaks.append(find_Bragg_disks_single_DP_FK(DP, probe_kernel_FT,
                                                   corrPower = corrPower,
                                                   sigma = sigma,
                                                   edgeBoundary = edgeBoundary,
                                                   minRelativeIntensity = minRelativeIntensity,
                                                   minPeakSpacing = minPeakSpacing,
                                                   maxNumPeaks = maxNumPeaks,
                                                   subpixel = subpixel,
                                                   upsample_factor = upsample_factor))
    t = time()-t0
    print("Analyzed {} diffraction patterns in {}h {}m {}s".format(len(Rx), int(t/3600),
                                                                   int((t%3600)/60), int(t%60)))

    return tuple(peaks)


def find_Bragg_disks(datacube, probe,
                     corrPower = 1,
                     sigma = 2,
                     edgeBoundary = 20,
                     minRelativeIntensity = 0.005,
                     minPeakSpacing = 60,
                     maxNumPeaks = 70,
                     subpixel = 'poly',
                     upsample_factor = 4,
                     verbose = False):
    """
    Finds the Bragg disks in all diffraction patterns of datacube by cross, hybrid, or phase
    correlation with probe.

    Accepts:
        DP                   (ndarray) a diffraction pattern
        probe                (ndarray) the vacuum probe template, in real space.
        corrPower            (float between 0 and 1, inclusive) the cross correlation power. A
                             value of 1 corresponds to a cross correaltion, and 0 corresponds to a
                             phase correlation, with intermediate values giving various hybrids.
        sigma                (float) the standard deviation for the gaussian smoothing applied to
                             the cross correlation
        edgeBoundary         (int) minimum acceptable distance from the DP edge, in pixels
        minRelativeIntensity (float) the minimum acceptable correlation peak intensity, relative to
                             the intensity of the brightest peak
        minPeakSpacing       (float) the minimum acceptable spacing between detected peaks
        maxNumPeaks          (int) the maximum number of peaks to return
        subpixel             (str)          'none': no subpixel fitting
                                    default 'poly': polynomial interpolation of correlogram peaks
                                                    (fairly fast but not very accurate)
                                            'multicorr': uses the multicorr algorithm with 
                                                        DFT upsampling
        upsample_factor      (int) upsampling factor for subpixel fitting (only used when subpixel='multicorr')
        verbose              (bool) if True, prints completion updates

    Returns:
        peaks                (PointListArray) the Bragg peak positions and correlation intensities
    """
    # Make the peaks PointListArray
    coords = [('qx',float),('qy',float),('intensity',float)]
    peaks = PointListArray(coordinates=coords, shape=(datacube.R_Nx, datacube.R_Ny))

    # Get the probe kernel FT
    probe_kernel_FT = np.conj(np.fft.fft2(probe))

    # Loop over all diffraction patterns
    t0 = time()
    for Rx in range(datacube.R_Nx):
        for Ry in range(datacube.R_Ny):
            if verbose:
                print_progress_bar(Rx*datacube.R_Ny+Ry+1, datacube.R_Nx*datacube.R_Ny,
                                   prefix='Analyzing:', suffix='Complete', length=50)
            DP = datacube.data[Rx,Ry,:,:]
            find_Bragg_disks_single_DP_FK(DP, probe_kernel_FT,
                                          corrPower = corrPower,
                                          sigma = sigma,
                                          edgeBoundary = edgeBoundary,
                                          minRelativeIntensity = minRelativeIntensity,
                                          minPeakSpacing = minPeakSpacing,
                                          maxNumPeaks = maxNumPeaks,
                                          subpixel = subpixel,
                                          upsample_factor = upsample_factor,
                                          peaks = peaks.get_pointlist(Rx,Ry))
    t = time()-t0
    print("Analyzed {} diffraction patterns in {}h {}m {}s".format(datacube.R_N, int(t/3600),
                                                                   int(t/60), int(t%60)))

    return peaks


def threshold_Braggpeaks(pointlistarray, minRelativeIntensity, minPeakSpacing, maxNumPeaks):
    """
    Takes a PointListArray of detected Bragg peaks and applies additional thresholding, returning
    the thresholded PointListArray. To skip a threshold, set that parameter to False.

    Accepts:
        pointlistarray        (PointListArray) The Bragg peaks.
                              Must have coords=('qx','qy','intensity')
        maxNumPeaks           (int) maximum number of allowed peaks per diffraction pattern
        minPeakSpacing        (int) the minimum allowed spacing between adjacent peaks
        minRelativeIntensity  (float) the minimum allowed peak intensity, relative to the brightest
                              peak in each diffraction pattern
    """
    assert all([item in pointlistarray.dtype.fields for item in ['qx','qy','intensity']]), "pointlistarray must include the coordinates 'qx', 'qy', and 'intensity'."
    for Rx in range(pointlistarray.shape[0]):
        for Ry in range(pointlistarray.shape[1]):
            pointlist = pointlistarray.get_pointlist(Rx,Ry)
            pointlist.sort(coordinate='intensity', order='descending')

            # Remove peaks below minRelativeIntensity threshold
            if minRelativeIntensity is not False:
                deletemask = pointlist.data['intensity']/max(pointlist.data['intensity']) < \
                                                                               minRelativeIntensity
                pointlist.remove_points(deletemask)

            # Remove peaks that are too close together
            if maxNumPeaks is not False:
                r2 = minPeakSpacing**2
                deletemask = np.zeros(pointlist.length, dtype=bool)
                for i in range(pointlist.length):
                    if deletemask[i] == False:
                        tooClose = ( (pointlist.data['qx']-pointlist.data['qx'][i])**2 + \
                                     (pointlist.data['qy']-pointlist.data['qy'][i])**2 ) < r2
                        tooClose[:i+1] = False
                        deletemask[tooClose] = True
                pointlist.remove_points(deletemask)

            # Keep only up to maxNumPeaks
            if maxNumPeaks is not False:
                if maxNumPeaks < pointlist.length:
                    deletemask = np.zeros(pointlist.length, dtype=bool)
                    deletemask[maxNumPeaks:] = True
                    pointlist.remove_points(deletemask)

    return pointlistarray


