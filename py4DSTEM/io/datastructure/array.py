# Defines the Array class, which stores any N-dimensional array-like data.
# Implements the EMD file standard - https://emdatasets.com/format

from typing import Optional,Union
import numpy as np
import h5py
from numbers import Number

from .ioutils import determine_group_name

class Array:
    """
    A class which stores any N-dimensional array-like data, plus basic metadata:
    a name and units, as well as calibrations for each axis of the array, and names
    and units for those axis calibrations.

    In the simplest usage, only a data array is passed:

    >>> ar = Array(np.ones((20,20,256,256)))

    will create an array instance whose data is the numpy array passed, and with
    automatically populated dimension calibrations in units of pixels.

    Additional arguments may be passed to populate the object metadata:

    >>> ar = Array(
    >>>     np.ones((20,20,256,256)),
    >>>     name = 'test_array',
    >>>     units = 'intensity',
    >>>     dims = [
    >>>         [0,5],
    >>>         [0,5],
    >>>         [0,0.01],
    >>>         [0,0.01]
    >>>     ],
    >>>     dim_units = [
    >>>         'nm',
    >>>         'nm',
    >>>         'A^-1',
    >>>         'A^-1'
    >>>     ],
    >>>     dim_names = [
    >>>         'rx',
    >>>         'ry',
    >>>         'qx',
    >>>         'qy'
    >>>     ],
    >>> )

    will create an array with a name and units for its data, with its first two
    dimensions in units of nanometers, with each pixel having a size of 5nm, and
    described by the handles 'rx' and 'ry', here meant to represent the (x,y)
    position in real space, and with its last two dimensions in units of inverse
    Angstroms, with each pixel having a size of 0.01A^-1, and dsecribed by the
    handles 'qx' and 'qy', representing the (x,y) position in diffraction space.

    Arrays in which the length of each pixel is non-constant are also
    supported.  For instance,

    >>> x = np.logspace(0,1,100)
    >>> y = np.sin(x)
    >>> ar = Array(
    >>>     y,
    >>>     dims = [
    >>>         x
    >>>     ]
    >>> )

    generates an array representing the values of the sine function sampled
    along a logarithmic interval from 1 to 10. In this example, this data
    could then be plotted with, e.g.

    >>> plt.scatter(ar.dims[0], ar.data)

    If the `slicelabels` keyword is passed, the first N-1 dimensions of the
    array are treated normally, while the final dimension is used to represent
    distinct arrays which share a common shape and set of dim vectors.  Thus

    >>> ar = Array(
    >>>     np.ones((50,50,4)),
    >>>     name = 'test_array_stack',
    >>>     units = 'intensity',
    >>>     dims = [
    >>>         [0,2],
    >>>         [0,2]
    >>>     ],
    >>>     dim_units = [
    >>>         'nm',
    >>>         'nm'
    >>>     ],
    >>>     dim_names = [
    >>>         'rx',
    >>>         'ry'
    >>>     ],
    >>>     slicelabels = [
    >>>         'a',
    >>>         'b',
    >>>         'c',
    >>>         'd'
    >>>     ]
    >>> )

    will generate a single Array instance containing 4 arrays which each have
    a shape (50,50) and a common set of dim vectors ['rx','ry'], and which
    can be indexed into with the names assigned in `slicelabels` using

    >>> ar.get_slice('a')

    which will return a rank 2 (non-stack-like) Array instance with shape (50,50)
    and the dims assigned above.

    """
    def __init__(
        self,
        data: np.ndarray,
        name: Optional[str] = 'array',
        units: Optional[str] = '',
        dims: Optional[list] = None,
        dim_names: Optional[list] = None,
        dim_units: Optional[list] = None,
        slicelabels = None
        ):
        """
        Accepts:
            data (np.ndarray): the data
            name (str): the name of the Array
            units (str): units for the pixel values
            dims (list): calibration vectors for each of the axes of the data
                array.  Valid values for each element of the list are None,
                a number, a 2-element list/array, or an M-element list/array
                where M is the data array.  If None is passed, the dim will be
                populated with integer values starting at 0 and its units will
                be set to pixels.  If a number is passed, the dim is populated
                with a vector beginning at zero and increasing linearly by this
                step size.  If a 2-element list/array is passed, the dim is
                populated with a linear vector with these two numbers as the first
                two elements.  If a list/array of length M is passed, this is used
                as the dim vector.  If dims recieves a list of fewer than N
                arguments for an N-dimensional data array, the extra dimensions
                are populated as if None were passed, using integer pixel values.
                If the `dims` parameter is not passed, all dim vectors are
                populated this way.
            dim_units (list): the units for the calibration dim vectors. If
                nothing is passed, dims vectors which have been populated
                automatically with integers corresponding to pixel numbers
                will be assigned units of 'pixels', and any other dim vectors
                will be assigned units of 'unknown'.  If a list with length <
                the array dimensions, the passed values are assumed to apply
                to the first N dimensions, and the remaining values are
                populated with 'pixels' or 'unknown' as above.
            dim_names (list): labels for each axis of the data array. Values
                which are not passed, following the same logic as described
                above, will be autopopulated with the name "dim#" where #
                is the axis number.
            slicelabels (None or True or list): if not None, must be True or a
                list of strings. The array rank will be taken to be
                `len(data.shape) - 1`, i.e. all dimensions except the last will be
                treated normally with respect to populating dims, dim_names, and
                dim_units, while the final dimension will be treated distinctly:
                it will index into functionally distinct arrays which share a set
                of dimension attributes, and can be sliced into using the string
                labels from the `slicelabels` list, with the syntax
                array.get_slice('label').  If `len(slicelabels)` is `True` or has
                length less than the final dimension length, unassigned dimensions
                will be autopopulated with labels `array{i}`. The flag array.is_stack
                will be set to True.

        Returns:
            A new Array instance
        """
        self.data = data
        self.name = name
        self.units = units
        self.dims = dims
        self.dim_names = dim_names
        self.dim_units = dim_units

        self.shape = self.data.shape
        self.rank = len(self.shape)

        # flags to help assign dim names and units
        dim_in_pixels = np.zeros(self.rank, dtype=bool)


        ## Handle array stacks

        if slicelabels is None:
            self.depth = 0
            self.is_stack = False

        else:
            self.depth = self.shape[-1]
            self.shape = self.shape[:-1]
            self.rank -= 1
            self.is_stack = True

            # Populate labels
            if slicelabels is True:
                slicelabels = [f'array{i}' for i in range(self.depth)]
            elif len(slicelabels) < self.depth:
                slicelabels = np.concatenate((slicelabels,
                    [f'array{i}' for i in range(len(slicelabels),self.depth)]))
            else:
                slicelabels = slicelabels[:self.depth]
            slicelabels = Labels(slicelabels)

        self.slicelabels = slicelabels


        ## Set dim vectors

        # if none were passed
        if self.dims is None:
            self.dims = [self._unpack_dim(1,self,shape[n]) for n in range(self.rank)]
            dim_in_pixels[:] = True

        # if some but not all were passed
        elif len(self.dims)<self.rank:
            _dims = self.dims
            N = len(_dims)
            self.dims = []
            for n in range(N):
                dim = self._unpack_dim(_dims[n],self.shape[n])
                self.dims.append(dim)
            for n in range(N,self.rank):
                self.dims.append(np.arange(self.shape[n]))
                dim_in_pixels[n] = True

        # if all were passed
        elif len(self.dims)==self.rank:
            _dims = self.dims
            self.dims = []
            for n in range(self.rank):
                dim = self._unpack_dim(_dims[n],self.shape[n])
                self.dims.append(dim)

        # otherwise
        else:
            raise Exception(f"too many dim vectors were passed - expected {self.rank}, received {len(self.dims)}")


        ## set dim vector names

        # if none were passed
        if self.dim_names is None:
            self.dim_names = [f"dim{n}" for n in range(self.rank)]

        # if some but not all were passed
        elif len(self.dim_names)<self.rank:
            N = len(self.dim_names)
            self.dim_names = [name for name in self.dim_names] + \
                             [f"dim{n}" for n in range(N,self.rank)]

        # if all were passed
        elif len(self.dim_names)==self.rank:
            pass

        # otherwise
        else:
            raise Exception(f"too many dim names were passed - expected {self.rank}, received {len(self.dim_names)}")


        ## set dim vector units

        # if none were passed
        if self.dim_units is None:
            self.dim_units = [['unknown','pixels'][i] for i in dim_in_pixels]

        # if some but not all were passed
        elif len(self.dim_units)<self.rank:
            N = len(self.dim_units)
            self.dim_units = [units for units in self.dim_units] + \
                             [['unknown','pixels'][dim_in_pixels[i]] for i in range(N,self.rank)]

        # if all were passed
        elif len(self.dim_units)==self.rank:
            pass

        # otherwise
        else:
            raise Exception(f"too many dim units were passed - expected {self.rank}, received {len(self.dim_units)}")




    #### Methods


    ## For slicing into array stacks

    def get_slice(self,label,name=None):
        idx = self.slicelabels._dict[label]
        return Array(
            data = self.data[..., idx],
            name = name if name is not None else self.name+'_'+label,
            units = self.units[:-1],
            dims = self.dims[:-1],
            dim_units = self.dim_units[:-1],
            dim_names = self.dim_names[:-1]
        )


    ## For dim vector handling

    def set_dim(
        self,
        n:int,
        dim:Union[list,np.ndarray],
        units:Optional[str]=None,
        name:Optional[str]=None
        ):
        """
        Sets the n'th dim vector, using `dim` as described in the Array documentation.
        If `units` and/or `name` are passed, sets these values for the n'th dim vector.

        Accepts:
            n (int): specifies which dim vector
            dim (list or array): length must be either 2, or equal to the length of
                the n'th axis of the data array
            units (Optional, str):
            name: (Optional, str):
        """
        length = self.shape[n]
        _dim = self._unpack_dim(dim,length)
        self.dims[n] = _dim
        if units is not None: self.dim_units[n] = units
        if name is not None: self.dim_names[n] = name



    @staticmethod
    def _unpack_dim(dim,length):
        """
        Given a dim vector as passed at instantiation and the expected length of this
        dimension of the array, this function checks the passed dim vector length, and
        checks the dim vector type.  For number-like dim-vectors:

        -if it is a number, turns it into the list [0,number] and proceeds as below

        -if it has length 2, linearly extends the vector to its full length

        -if it has length `length`, returns the vector as is

        -if it has any other length, raises an Exception.

        For string-like dim vectors, the length must match the array dimension length.

        Accepts:
            dim (list or array)
            length (int)

        Returns
            the unpacked dim vector
        """
        # Expand single numbers
        if isinstance(dim,Number):
            dim = [0,dim]

        N = len(dim)

        # for string dimensions:
        if not isinstance(dim[0],Number):
            assert(N == length), f"For non-numerical dims, the dim vector length must match the array dimension length. Recieved a dim vector of length {N} for an array dimension length of {length}."

        # For number-like dimensions:
        if N == length:
            return dim
        elif N == 2:
            start,step = dim[0],dim[1]-dim[0]
            stop = start + step*length
            return np.arange(start,stop,step)
        else:
            raise Exception(f"dim vector length must be either 2 or equal to the length of the corresponding array dimension; dim vector length was {dim} and the array dimension length was {length}")


    def _dim_is_linear(self,dim,length):
        """
        Returns True if a dim is linear, else returns False
        """
        dim_expanded = self._unpack_dim(dim[:2],length)
        return np.array_equal(dim,dim_expanded)


    ## Representation to standard output

    def __repr__(self):

        if not self.is_stack:
            space = ' '*len(self.__class__.__name__)+'  '
            string = f"{self.__class__.__name__}( A {self.rank}-dimensional array of shape {self.shape} called '{self.name}',"
            string += "\n"+space+"with dimensions:"
            string += "\n"
            for n in range(self.rank):
                string += "\n"+space+f"{self.dim_names[n]} = [{self.dims[n][0]},{self.dims[n][1]},...] {self.dim_units[n]}"
            string += "\n)"

        else:
            space = ' '*len(self.__class__.__name__)+'  '
            string = f"{self.__class__.__name__}( A stack of {self.depth} Arrays with {self.rank}-dimensions and shape {self.shape[:-1]}, called '{self.name}'"
            string += "\n"
            string += "\n" +space + "The labels are:"
            for label in self.slicelabels:
                string += "\n" + space + f"    {label}"
            string += "\n"
            string += "\n"
            string += "\n" + space + "The Array dimensions are:"
            for n in range(self.rank):
                string += "\n"+space+f"    {self.dim_names[n]} = [{self.dims[n][0]},{self.dims[n][1]},...] {self.dim_units[n]}"
                if not self._dim_is_linear(self.dims[n],self.shape[n]):
                    string += "  (*non-linear*)"
            string += "\n)"

        return string



    ## Writing to an HDF5 file

    def to_h5(self,group):
        """
        Takes a valid HDF5 group for an HDF5 file object which is open in write or append
        mode. Writes a new group with a name given by this Array's .name field nested
        inside the passed group, and saves the data there.

        If the Array has no name, it will be assigned the name "Array#" where # is the
        lowest available integer.  If the Array's name already exists here in this file,
        raises and exception.

        TODO: add overwite option.

        Accepts:
            group (HDF5 group)
        """

        # Detemine the name of the group
        # if current name is invalid, raises and exception
        # TODO: add overwrite option
        determine_group_name(self, group)


        ## Write

        grp = group.create_group(self.name)
        grp.attrs.create("emd_group_type",1) # this tag indicates an Array type object
        grp.attrs.create("py4dstem_class",self.__class__.__name__)

        # add the data
        data = grp.create_dataset(
            "data",
            shape = self.data.shape,
            data = self.data,
            #dtype = type(self.data)
        )
        data.attrs.create('units',self.units) # save 'units' but not 'name' - 'name' is the group name

        # Add the normal dim vectors
        for n in range(self.rank):

            # unpack info
            dim = self.dims[n]
            name = self.dim_names[n]
            units = self.dim_units[n]
            is_linear = self._dim_is_linear(dim,self.shape[n])

            # compress the dim vector if it's linear
            if is_linear:
                dim = dim[:2]

            # write
            dset = grp.create_dataset(
                f"dim{n}",
                data = dim
            )
            dset.attrs.create('name',name)
            dset.attrs.create('units',units)

        # Add stack dim vector, if present
        if self.is_stack:
            n = self.rank
            name = '_labels_'
            dim = [s.encode('utf-8') for s in self.slicelabels]

            # write
            dset = grp.create_dataset(
                f"dim{n}",
                data = dim
            )
            dset.attrs.create('name',name)



########### END OF CLASS ###########


# List subclass for accessing data slices with a dict
class Labels(list):
    def __init__(self,x=[]):
        list.__init__(self,x)
        self.setup_labels_dict()
    def __setitem__(self,idx,label):
        list.__setitem__(self,idx,label)
        self.setup_labels_dict()

    def setup_labels_dict(self):
        self._dict = {}
        for idx,label in enumerate(self):
            self._dict[label] = idx



## Read Array objects

def Array_from_h5(group:h5py.Group, name:str):
    """
    Takes a valid HDF5 group for an HDF5 file object which is open in read mode,
    and a name.  Determines if a valid Array object of this name exists inside
    this group, and if it does, loads and returns it. If it doesn't, raises
    an exception.

    Accepts:
        group (HDF5 group)
        name (string)

    Returns:
        An Array instance
    """
    assert(Array_exists(group,name)), f"No Array called {name} could be found in group {group} of this HDF5 file."
    grp = group[name]

    # get data
    dset = grp['data']
    data = dset[:]
    units = dset.attrs['units']
    rank = len(data.shape)

    # determine if this is a stack array
    last_dim = grp[f"dim{rank-1}"]
    if last_dim.attrs['name'] == '_labels_':
        is_stack = True
        normal_dims = rank-1
    else:
        is_stack = False
        normal_dims = rank

    # get dim vectors
    dims = []
    dim_units = []
    dim_names = []
    for n in range(normal_dims):
        dim_dset = grp[f"dim{n}"]
        dims.append(dim_dset[:])
        dim_units.append(dim_dset.attrs['units'])
        dim_names.append(dim_dset.attrs['name'])

    # if it's a stack array, get the labels
    if is_stack:
        slicelabels = last_dim[:]
        slicelabels = [s.decode('utf-8') for s in slicelabels]
    else:
        slicelabels = None

    # make Array
    ar = Array(
        data = data,
        name = name,
        units = units,
        dims = dims,
        dim_names = dim_names,
        dim_units = dim_units,
        slicelabels = slicelabels
    )

    return ar


def find_Arrays(group:h5py.Group):
    """
    Takes a valid HDF5 group for an HDF5 file object which is open in read mode,
    and finds all Array groups inside this group at its top level. Does not do a search
    for nested Array groups. Returns the names of all Array groups found.

    Accepts:
        group (HDF5 group)
    """
    keys = [k for k in group.keys() if "emd_group_type" in group[k].attrs.keys()]
    return [k for k in keys if group[k].attrs["emd_group_type"] == 1]


def Array_exists(group:h5py.Group, name:str):
    """
    Takes a valid HDF5 group for an HDF5 file object which is open in read mode,
    and a name.  Determines if an Array object of this name exists inside this group,
    and returns a boolean.

    Accepts:
        group (HDF5 group)
        name (string)

    Returns:
        bool
    """
    if name in group.keys():
        if "emd_group_type" in group[name].attrs.keys():
            if group[name].attrs["emd_group_type"] == 1:
                return True
            return False
        return False
    return False





