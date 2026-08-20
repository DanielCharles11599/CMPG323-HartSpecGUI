from astropy.io import fits as pyfits
from astropy.io import ascii
import numpy as np
import matplotlib.pyplot as plt
import os
import pickle
from astropy.time import Time
from os import path
from astropy.time import Time
from scipy.optimize import curve_fit
from platform import python_version
#from builtins import str
import time
from astropy.modeling import models
from astropy import units as u
#from specutils.spectra import Spectrum1D
#from specutils.fitting import fit_lines


def plot_spec(spec):
    """ Produce spectral plots given spectral line data"""
    plt.plot(spec['Vlsr'], spec['LCP'], label='LCP')
    plt.plot(spec['Vlsr'], spec['RCP'], label='RCP')
    plt.legend()
    plt.title(spec['object'] + ' ' + spec['date'])
    plt.xlabel('V_lsr (km/s)')
    plt.ylabel('Antenna temperature (K)')
    plt.axis('tight')
    plt.savefig("../plots/Flattend_Spec_%s.pdf" % spec['object'], bbox_inches='tight')
    plt.draw()
    plt.pause(0.001)