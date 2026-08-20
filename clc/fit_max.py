from astropy.io import fits as pyfits
from astropy.io import ascii
import numpy as np
import matplotlib.pyplot as plt
import os
import pickle
from astropy.time import Time
from os import path
import numpy as np
from astropy.time import Time
from scipy.optimize import curve_fit
from platform import python_version
#from builtins import str
import time
from astropy.modeling import models
from astropy import units as u
#from specutils.spectra import Spectrum1D
#from specutils.fitting import fit_lines

def fit_max(spec, peak_vel, half_width, order):
    """
    Inputs:
        spec : a spectrum with columns 'Vlsr' and 'Amp'
        peak_vel : velocity at which to fit the maximum amplitdue
        half_width : How many channels to include on either side of the peak velocity.
                     This will depend on the width of the maser peak and 
                     how well a quadratic function fits the top of the peak
                     
    Returns:
        maximim amplitude
    """
    print("# ================================================================= #")
    print("# Now starting with gaussian fitting to the pointing peaks          #")
    print("# ================================================================= #")
    
    vel_chan = np.abs(spec['Vlsr']-peak_vel).argmin()
    
    #for noisy spectra - ie weak sources, it is better to do a quadratic fit over a few channels around the peak.
    chans = range(vel_chan-half_width, vel_chan+half_width)
    
    p = np.poly1d(np.polyfit(spec['Vlsr'][chans], spec['ave_pol'][chans], order ))
    fit_x = np.linspace(spec['Vlsr'][min(chans)], spec['Vlsr'][max(chans)], 50)
        
    fit = p(fit_x)
    #plt.plot(fit_x, fit, 'r')
    #plt.plot(fit_x2, fit2, 'r')
    #plt.xlabel("Vlsr (km/s)")
    #plt.savefig('fit_max.png')
    #plt.show()
    #plt.close()
    return  chans,  fit.max(), fit_x, fit
    
