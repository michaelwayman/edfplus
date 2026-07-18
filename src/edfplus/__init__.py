"""EDF/EDF+ file reader library.

Provides a typed Python API for reading and working with EDF (European Data Format)
and EDF+ biosignal recordings including EEG, PSG, and other physiological time-series
data.

Example:
    >>> from edfplus import read_edf
    >>> with read_edf("recording.edf") as edf:
    ...     print(edf.signals[0].samples)
"""

from edfplus._models import Annotation, EDFFile, EDFHeader, Signal
from edfplus.reader import read_edf

__all__ = ["read_edf", "EDFFile", "EDFHeader", "Signal", "Annotation"]
