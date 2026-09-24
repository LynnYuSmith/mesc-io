"""Read Femtonics `.mesc` two-photon recordings, in the units the native reader shows."""
from .errors import MescIOError
from .reader import Channel, MescError, MescFile, Unit
from .values import ConversionError, from_reader_units, to_reader_units

__version__ = "0.2.1"
__all__ = ["MescFile", "Unit", "Channel", "MescError", "MescIOError",
           "to_reader_units", "from_reader_units", "ConversionError", "__version__"]
