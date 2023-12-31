from typing import Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec
from mpl_toolkits.axes_grid1 import make_axes_locatable
from py4DSTEM.process.phase.utils import AffineTransform, rotate_point
from py4DSTEM.visualize import return_scaled_histogram_ordering, show, show_complex
from scipy.ndimage import gaussian_filter, rotate

try:
    import cupy as cp
except (ModuleNotFoundError, ImportError):
    cp = np


class ObjectNDMethodsMixin:
    """
    Mixin class for object methods applicable to 2D,2.5D, and 3D objects.
    """

    def _crop_rotate_object_fov(
        self,
        array,
        padding=0,
    ):
        """
        Crops and rotated object to FOV bounded by current pixel positions.

        Parameters
        ----------
        array: np.ndarray
            Object array to crop and rotate. Only operates on numpy arrays for compatibility.
        padding: int, optional
            Optional padding outside pixel positions

        Returns
        cropped_rotated_array: np.ndarray
            Cropped and rotated object array
        """

        asnumpy = self._asnumpy
        angle = (
            self._rotation_best_rad
            if self._rotation_best_transpose
            else -self._rotation_best_rad
        )

        tf = AffineTransform(angle=angle)
        rotated_points = tf(
            asnumpy(self._positions_px), origin=asnumpy(self._positions_px_com), xp=np
        )

        min_x, min_y = np.floor(np.amin(rotated_points, axis=0) - padding).astype("int")
        min_x = min_x if min_x > 0 else 0
        min_y = min_y if min_y > 0 else 0
        max_x, max_y = np.ceil(np.amax(rotated_points, axis=0) + padding).astype("int")

        rotated_array = rotate(
            asnumpy(array), np.rad2deg(-angle), order=1, reshape=False, axes=(-2, -1)
        )[..., min_x:max_x, min_y:max_y]

        if self._rotation_best_transpose:
            rotated_array = rotated_array.swapaxes(-2, -1)

        return rotated_array

    def _return_projected_cropped_potential(
        self,
    ):
        """Utility function to accommodate multiple classes"""
        if self._object_type == "complex":
            projected_cropped_potential = np.angle(self.object_cropped)
        else:
            projected_cropped_potential = self.object_cropped

        return projected_cropped_potential

    def _return_object_fft(
        self,
        obj=None,
    ):
        """
        Returns absolute value of obj fft shifted to center of array

        Parameters
        ----------
        obj: array, optional
            if None is specified, uses self._object

        Returns
        -------
        object_fft_amplitude: np.ndarray
            Amplitude of Fourier-transformed and center-shifted obj.
        """
        xp = self._xp
        asnumpy = self._asnumpy

        if obj is None:
            obj = self._object

        if np.iscomplexobj(obj):
            obj = xp.angle(obj)

        obj = self._crop_rotate_object_fov(asnumpy(obj))
        return np.abs(np.fft.fftshift(np.fft.fft2(obj)))

    def show_object_fft(self, obj=None, **kwargs):
        """
        Plot FFT of reconstructed object

        Parameters
        ----------
        obj: complex array, optional
            if None is specified, uses the `object_fft` property
        """
        if obj is None:
            object_fft = self.object_fft
        else:
            object_fft = self._return_object_fft(obj)

        figsize = kwargs.pop("figsize", (6, 6))
        cmap = kwargs.pop("cmap", "magma")

        pixelsize = 1 / (object_fft.shape[1] * self.sampling[1])
        show(
            object_fft,
            figsize=figsize,
            cmap=cmap,
            scalebar=True,
            pixelsize=pixelsize,
            ticks=False,
            pixelunits=r"$\AA^{-1}$",
            **kwargs,
        )

    @property
    def object_fft(self):
        """Fourier transform of current object estimate"""

        if not hasattr(self, "_object"):
            return None

        return self._return_object_fft(self._object)

    @property
    def object_cropped(self):
        """Cropped and rotated object"""

        return self._crop_rotate_object_fov(self._object)


class Object2p5DMethodsMixin:
    """
    Mixin class for object methods unique to 2.5D objects.
    Overwrites ObjectNDMethodsMixin.
    """

    def _return_projected_cropped_potential(
        self,
    ):
        """Utility function to accommodate multiple classes"""
        if self._object_type == "complex":
            projected_cropped_potential = np.angle(self.object_cropped).sum(0)
        else:
            projected_cropped_potential = self.object_cropped.sum(0)

        return projected_cropped_potential

    def _return_object_fft(
        self,
        obj=None,
    ):
        """
        Returns obj fft shifted to center of array

        Parameters
        ----------
        obj: array, optional
            if None is specified, uses self._object
        """
        xp = self._xp

        if obj is None:
            obj = self._object

        if np.iscomplexobj(obj):
            obj = xp.angle(obj)

        obj = self._crop_rotate_object_fov(obj.sum(axis=0))
        return np.abs(np.fft.fftshift(np.fft.fft2(obj)))

    def show_depth_section(
        self,
        ptA: Tuple[float, float],
        ptB: Tuple[float, float],
        aspect_ratio: float = "auto",
        plot_line_profile: bool = False,
        ms_object=None,
        specify_calibrated: bool = True,
        gaussian_filter_sigma: float = None,
        cbar: bool = True,
        **kwargs,
    ):
        """
        Displays line profile depth section

        Parameters
        ----------
        ptA: Tuple[float,float]
            Starting point (x1,y1) for line profile depth section
            If either is None, assumed to be array start.
            Specified in Angstroms unless specify_calibrated is False
        ptB: Tuple[float,float]
            End point (x2,y2) for line profile depth section
            If either is None, assumed to be array end.
            Specified in Angstroms unless specify_calibrated is False
        aspect_ratio: float, optional
            aspect ratio for depth profile plot
        plot_line_profile: bool
            If True, also plots line profile showing where depth profile is taken
        ms_object: np.array
            Object to plot slices of. If None, uses current object
        specify_calibrated: bool (optional)
            If False, ptA and ptB points specified in pixels instead of Angstroms
        gaussian_filter_sigma: float (optional)
            Standard deviation of gaussian kernel in A
        cbar: bool, optional
            If True, displays a colorbar
        """
        if ms_object is None:
            ms_object = self.object_cropped

        if np.iscomplexobj(ms_object):
            ms_object = np.angle(ms_object)

        x1, y1 = ptA
        x2, y2 = ptB

        if x1 is None:
            x1 = 0
        if y1 is None:
            y1 = 0
        if x2 is None:
            x2 = self.sampling[0] * ms_object.shape[1]
        if y2 is None:
            y2 = self.sampling[1] * ms_object.shape[2]

        if specify_calibrated:
            x1 /= self.sampling[0]
            x2 /= self.sampling[0]
            y1 /= self.sampling[1]
            y2 /= self.sampling[1]

        x1, x2 = np.array([x1, x2]).clip(0, ms_object.shape[1])
        y1, y2 = np.array([y1, y2]).clip(0, ms_object.shape[2])

        angle = np.arctan2(x2 - x1, y2 - y1)

        x0 = ms_object.shape[1] / 2
        y0 = ms_object.shape[2] / 2

        x1_0, y1_0 = rotate_point((x0, y0), (x1, y1), angle)
        x2_0, y2_0 = rotate_point((x0, y0), (x2, y2), angle)

        rotated_object = np.roll(
            rotate(ms_object, np.rad2deg(angle), reshape=False, axes=(-1, -2)),
            -int(x1_0),
            axis=1,
        )

        if gaussian_filter_sigma is not None:
            gaussian_filter_sigma /= self.sampling[0]
            rotated_object = gaussian_filter(rotated_object, gaussian_filter_sigma)

        y1_0, y2_0 = (
            np.array([y1_0, y2_0]).astype("int").clip(0, rotated_object.shape[2])
        )
        plot_im = rotated_object[:, 0, y1_0:y2_0]

        # Plotting
        if plot_line_profile:
            ncols = 2
        else:
            ncols = 1
        col_index = 0

        spec = GridSpec(ncols=ncols, nrows=1, wspace=0.15)

        figsize = kwargs.pop("figsize", (4 * ncols, 4))
        fig = plt.figure(figsize=figsize)
        cmap = kwargs.pop("cmap", "magma")

        # Line profile
        if plot_line_profile:
            ax = fig.add_subplot(spec[0, col_index])

            extent_line = [
                0,
                self.sampling[1] * ms_object.shape[2],
                self.sampling[0] * ms_object.shape[1],
                0,
            ]

            ax.imshow(ms_object.sum(0), cmap="gray", extent=extent_line)

            ax.plot(
                [y1 * self.sampling[0], y2 * self.sampling[1]],
                [x1 * self.sampling[0], x2 * self.sampling[1]],
                color="red",
            )

            ax.set_xlabel("y [A]")
            ax.set_ylabel("x [A]")
            ax.set_title("Multislice depth profile location")
            col_index += 1

        # Main visualization

        extent = [
            0,
            self.sampling[1] * plot_im.shape[1],
            self._slice_thicknesses[0] * plot_im.shape[0],
            0,
        ]

        ax = fig.add_subplot(spec[0, col_index])
        im = ax.imshow(plot_im, cmap=cmap, extent=extent)

        if aspect_ratio is not None:
            if aspect_ratio == "auto":
                aspect_ratio = extent[1] / extent[2]
                if plot_line_profile:
                    aspect_ratio *= extent_line[2] / extent_line[1]

            ax.set_aspect(aspect_ratio)
            cbar = False

        ax.set_xlabel("r [A]")
        ax.set_ylabel("z [A]")
        ax.set_title("Multislice depth profile")

        if cbar:
            divider = make_axes_locatable(ax)
            ax_cb = divider.append_axes("right", size="5%", pad="2.5%")
            fig.add_axes(ax_cb)
            fig.colorbar(im, cax=ax_cb)

        spec.tight_layout(fig)

    def show_slices(
        self,
        ms_object=None,
        cbar: bool = True,
        common_color_scale: bool = True,
        padding: int = 0,
        num_cols: int = 3,
        show_fft: bool = False,
        **kwargs,
    ):
        """
        Displays reconstructed slices of object

        Parameters
        --------
        ms_object: nd.array, optional
            Object to plot slices of. If None, uses current object
        cbar: bool, optional
            If True, displays a colorbar
        padding: int, optional
            Padding to leave uncropped
        num_cols: int, optional
            Number of GridSpec columns
        show_fft: bool, optional
            if True, plots fft of object slices
        """

        if ms_object is None:
            ms_object = self._object

        rotated_object = self._crop_rotate_object_fov(ms_object, padding=padding)
        if show_fft:
            rotated_object = np.abs(
                np.fft.fftshift(
                    np.fft.fft2(rotated_object, axes=(-2, -1)), axes=(-2, -1)
                )
            )
        rotated_shape = rotated_object.shape

        if np.iscomplexobj(rotated_object):
            rotated_object = np.angle(rotated_object)

        extent = [
            0,
            self.sampling[1] * rotated_shape[2],
            self.sampling[0] * rotated_shape[1],
            0,
        ]

        num_rows = np.ceil(self._num_slices / num_cols).astype("int")
        wspace = 0.35 if cbar else 0.15

        axsize = kwargs.pop("axsize", (3, 3))
        cmap = kwargs.pop("cmap", "magma")

        if common_color_scale:
            vmin = kwargs.pop("vmin", None)
            vmax = kwargs.pop("vmax", None)
            rotated_object, vmin, vmax = return_scaled_histogram_ordering(
                rotated_object, vmin=vmin, vmax=vmax
            )
        else:
            vmin = None
            vmax = None

        spec = GridSpec(
            ncols=num_cols,
            nrows=num_rows,
            hspace=0.15,
            wspace=wspace,
        )

        figsize = (axsize[0] * num_cols, axsize[1] * num_rows)
        fig = plt.figure(figsize=figsize)

        for flat_index, obj_slice in enumerate(rotated_object):
            row_index, col_index = np.unravel_index(flat_index, (num_rows, num_cols))
            ax = fig.add_subplot(spec[row_index, col_index])
            im = ax.imshow(
                obj_slice,
                cmap=cmap,
                vmin=vmin,
                vmax=vmax,
                extent=extent,
                **kwargs,
            )

            ax.set_title(f"Slice index: {flat_index}")

            if cbar:
                divider = make_axes_locatable(ax)
                ax_cb = divider.append_axes("right", size="5%", pad="2.5%")
                fig.add_axes(ax_cb)
                fig.colorbar(im, cax=ax_cb)

            if row_index < num_rows - 1:
                ax.set_xticks([])
            else:
                ax.set_xlabel("y [A]")

            if col_index > 0:
                ax.set_yticks([])
            else:
                ax.set_ylabel("x [A]")

        spec.tight_layout(fig)


class Object3DMethodsMixin:
    """
    Mixin class for object methods unique to 3D objects.
    Overwrites ObjectNDMethodsMixin and Object2p5DMethodsMixin.
    """

    def _crop_rotate_object_manually(
        self,
        array,
        angle,
        x_lims,
        y_lims,
    ):
        """
        Crops and rotates rotates object manually.

        Parameters
        ----------
        array: np.ndarray
            Object array to crop and rotate. Only operates on numpy arrays for compatibility.
        angle: float
            In-plane angle in degrees to rotate by
        x_lims: tuple(float,float)
            min/max x indices
        y_lims: tuple(float,float)
            min/max y indices

        Returns
        -------
        cropped_rotated_array: np.ndarray
            Cropped and rotated object array
        """

        asnumpy = self._asnumpy
        min_x, max_x = x_lims
        min_y, max_y = y_lims

        if angle is not None:
            rotated_array = rotate(asnumpy(array), angle, reshape=False, axes=(-2, -1))
        else:
            rotated_array = asnumpy(array)

        return rotated_array[..., min_x:max_x, min_y:max_y]

    def _return_projected_cropped_potential(
        self,
    ):
        """Utility function to accommodate multiple classes"""
        raise NotImplementedError()

    def _return_object_fft(
        self,
        obj=None,
        projection_angle_deg: float = None,
        projection_axes: Tuple[int, int] = (0, 2),
        x_lims: Tuple[int, int] = (None, None),
        y_lims: Tuple[int, int] = (None, None),
    ):
        """
        Returns obj fft shifted to center of array

        Parameters
        ----------
        obj: array, optional
            if None is specified, uses self._object
        projection_angle_deg: float
            Angle in degrees to rotate 3D array around prior to projection
        projection_axes: tuple(int,int)
            Axes defining projection plane
        x_lims: tuple(float,float)
            min/max x indices
        y_lims: tuple(float,float)
            min/max y indices
        """

        xp = self._xp
        asnumpy = self._asnumpy

        if obj is None:
            obj = self._object
        else:
            obj = xp.asarray(obj, dtype=xp.float32)

        if projection_angle_deg is not None:
            rotated_3d_obj = self._rotate(
                obj,
                projection_angle_deg,
                axes=projection_axes,
                reshape=False,
                order=2,
            )
            rotated_3d_obj = asnumpy(rotated_3d_obj)
        else:
            rotated_3d_obj = asnumpy(obj)

        rotated_object = self._crop_rotate_object_manually(
            rotated_3d_obj.sum(0), angle=None, x_lims=x_lims, y_lims=y_lims
        )

        return np.abs(np.fft.fftshift(np.fft.fft2(rotated_object)))

    def show_object_fft(
        self,
        obj=None,
        projection_angle_deg: float = None,
        projection_axes: Tuple[int, int] = (0, 2),
        x_lims: Tuple[int, int] = (None, None),
        y_lims: Tuple[int, int] = (None, None),
        **kwargs,
    ):
        """
        Plot FFT of reconstructed object

        Parameters
        ----------
        obj: array, optional
            if None is specified, uses self._object
        projection_angle_deg: float
            Angle in degrees to rotate 3D array around prior to projection
        projection_axes: tuple(int,int)
            Axes defining projection plane
        x_lims: tuple(float,float)
            min/max x indices
        y_lims: tuple(float,float)
            min/max y indices
        """
        if obj is None:
            object_fft = self._return_object_fft(
                projection_angle_deg=projection_angle_deg,
                projection_axes=projection_axes,
                x_lims=x_lims,
                y_lims=y_lims,
            )
        else:
            object_fft = self._return_object_fft(
                obj,
                projection_angle_deg=projection_angle_deg,
                projection_axes=projection_axes,
                x_lims=x_lims,
                y_lims=y_lims,
            )

        figsize = kwargs.pop("figsize", (6, 6))
        cmap = kwargs.pop("cmap", "magma")

        pixelsize = 1 / (object_fft.shape[1] * self.sampling[1])
        show(
            object_fft,
            figsize=figsize,
            cmap=cmap,
            scalebar=True,
            pixelsize=pixelsize,
            ticks=False,
            pixelunits=r"$\AA^{-1}$",
            **kwargs,
        )


class ProbeMethodsMixin:
    """
    Mixin class for probe methods applicable to a single probe.
    """

    def _return_fourier_probe(
        self,
        probe=None,
        remove_initial_probe_aberrations=False,
    ):
        """
        Returns complex fourier probe shifted to center of array from
        corner-centered complex real space probe

        Parameters
        ----------
        probe: complex array, optional
            if None is specified, uses self._probe
        remove_initial_probe_aberrations: bool, optional
            If True, removes initial probe aberrations from Fourier probe

        Returns
        -------
        fourier_probe: np.ndarray
            Fourier-transformed and center-shifted probe.
        """
        xp = self._xp

        if probe is None:
            probe = self._probe
        else:
            probe = xp.asarray(probe, dtype=xp.complex64)

        fourier_probe = xp.fft.fft2(probe)

        if remove_initial_probe_aberrations:
            fourier_probe *= xp.conjugate(self._known_aberrations_array)

        return xp.fft.fftshift(fourier_probe, axes=(-2, -1))

    def _return_fourier_probe_from_centered_probe(
        self,
        probe=None,
        remove_initial_probe_aberrations=False,
    ):
        """
        Returns complex fourier probe shifted to center of array from
        centered complex real space probe

        Parameters
        ----------
        probe: complex array, optional
            if None is specified, uses self._probe
        remove_initial_probe_aberrations: bool, optional
            If True, removes initial probe aberrations from Fourier probe

        Returns
        -------
        fourier_probe: np.ndarray
            Fourier-transformed and center-shifted probe.
        """
        xp = self._xp
        return self._return_fourier_probe(
            xp.fft.ifftshift(probe, axes=(-2, -1)),
            remove_initial_probe_aberrations=remove_initial_probe_aberrations,
        )

    def _return_centered_probe(
        self,
        probe=None,
    ):
        """
        Returns complex probe centered in middle of the array.

        Parameters
        ----------
        probe: complex array, optional
            if None is specified, uses self._probe

        Returns
        -------
        centered_probe: np.ndarray
            Center-shifted probe.
        """
        xp = self._xp

        if probe is None:
            probe = self._probe
        else:
            probe = xp.asarray(probe, dtype=xp.complex64)

        return xp.fft.fftshift(probe, axes=(-2, -1))

    def show_fourier_probe(
        self,
        probe=None,
        remove_initial_probe_aberrations=False,
        cbar=True,
        scalebar=True,
        pixelsize=None,
        pixelunits=None,
        **kwargs,
    ):
        """
        Plot probe in fourier space

        Parameters
        ----------
        probe: complex array, optional
            if None is specified, uses the `probe_fourier` property
        remove_initial_probe_aberrations: bool, optional
            If True, removes initial probe aberrations from Fourier probe
        cbar: bool, optional
            if True, adds colorbar
        scalebar: bool, optional
            if True, adds scalebar to probe
        pixelunits: str, optional
            units for scalebar, default is A^-1
        pixelsize: float, optional
            default is probe reciprocal sampling
        """
        asnumpy = self._asnumpy

        probe = asnumpy(
            self._return_fourier_probe(
                probe, remove_initial_probe_aberrations=remove_initial_probe_aberrations
            )
        )

        if pixelsize is None:
            pixelsize = self._reciprocal_sampling[1]
        if pixelunits is None:
            pixelunits = r"$\AA^{-1}$"

        figsize = kwargs.pop("figsize", (6, 6))
        chroma_boost = kwargs.pop("chroma_boost", 1)

        fig, ax = plt.subplots(figsize=figsize)
        show_complex(
            probe,
            cbar=cbar,
            figax=(fig, ax),
            scalebar=scalebar,
            pixelsize=pixelsize,
            pixelunits=pixelunits,
            ticks=False,
            chroma_boost=chroma_boost,
            **kwargs,
        )

    @property
    def probe_fourier(self):
        """Current probe estimate in Fourier space"""
        if not hasattr(self, "_probe"):
            return None

        asnumpy = self._asnumpy
        return asnumpy(self._return_fourier_probe(self._probe))

    @property
    def probe_fourier_residual(self):
        """Current probe estimate in Fourier space"""
        if not hasattr(self, "_probe"):
            return None

        asnumpy = self._asnumpy
        return asnumpy(
            self._return_fourier_probe(
                self._probe, remove_initial_probe_aberrations=True
            )
        )

    @property
    def probe_centered(self):
        """Current probe estimate shifted to the center"""
        if not hasattr(self, "_probe"):
            return None

        asnumpy = self._asnumpy
        return asnumpy(self._return_centered_probe(self._probe))


class ProbeMixedMethodsMixin:
    """
    Mixin class for probe methods unique to mixed probes.
    Overwrites ProbeMethodsMixin.
    """

    def show_fourier_probe(
        self,
        probe=None,
        remove_initial_probe_aberrations=False,
        cbar=True,
        scalebar=True,
        pixelsize=None,
        pixelunits=None,
        **kwargs,
    ):
        """
        Plot probe in fourier space

        Parameters
        ----------
        probe: complex array, optional
            if None is specified, uses the `probe_fourier` property
        remove_initial_probe_aberrations: bool, optional
            If True, removes initial probe aberrations from Fourier probe
        scalebar: bool, optional
            if True, adds scalebar to probe
        pixelunits: str, optional
            units for scalebar, default is A^-1
        pixelsize: float, optional
            default is probe reciprocal sampling
        """
        asnumpy = self._asnumpy

        if probe is None:
            probe = list(
                asnumpy(
                    self._return_fourier_probe(
                        probe,
                        remove_initial_probe_aberrations=remove_initial_probe_aberrations,
                    )
                )
            )
        else:
            if isinstance(probe, np.ndarray) and probe.ndim == 2:
                probe = [probe]
            probe = [
                asnumpy(
                    self._return_fourier_probe(
                        pr,
                        remove_initial_probe_aberrations=remove_initial_probe_aberrations,
                    )
                )
                for pr in probe
            ]

        if pixelsize is None:
            pixelsize = self._reciprocal_sampling[1]
        if pixelunits is None:
            pixelunits = r"$\AA^{-1}$"

        chroma_boost = kwargs.pop("chroma_boost", 1)

        show_complex(
            probe if len(probe) > 1 else probe[0],
            cbar=cbar,
            scalebar=scalebar,
            pixelsize=pixelsize,
            pixelunits=pixelunits,
            ticks=False,
            chroma_boost=chroma_boost,
            **kwargs,
        )
