#------------------------------------------------------------------------------#
# Imports

from astropy.io import fits as pyfits
from astropy.io import ascii
from astropy.time import Time
from os import path
from astropy.time import Time
from scipy.optimize import curve_fit
from platform import python_version
from astropy.modeling import models
from astropy import units as u
#from specutils.spectra import Spectrum1D
#from specutils.fitting import fit_lines

import time
import numpy as np
import matplotlib.pyplot as plt
import os
import pickle


def gaussf(x, hp, *p):
    """
    Fits a 1-dimensional gaussian to the peaks of each pointing observation.
    
    To do: Create a 2-dimensional gaussian fitting algorithm for pointing correction calculations.  
    """
    #global hp
    hpbw = hp
    A, mu = p
    sigma = hpbw/(2*np.sqrt(2*np.log(2)))  #a bit messy but not sure how to pass a constant through the curve fitting
    return A*np.exp(-(x-mu)**2/(2.*sigma**2))