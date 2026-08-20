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
#from scipy.optimize import curve_fit
import time
from glob import glob
from astropy.modeling import models
from astropy import units as u
#from specutils.spectra import Spectrum1D
#from specutils.fitting import fit_lines
#import Gaussf as gf

def gaussf(x, *p):
    """
    Fits a 1-dimensional gaussian to the peaks of each pointing observation.
    To do: Create a 2-dimensional gaussian fitting algorithm for pointing correction calculations.  
    """
    global hp
    hpbw = hp
    A, mu = p
    sigma = hpbw/(2*np.sqrt(2*np.log(2)))  #a bit messy but not sure how to pass a constant through the curve fitting
    return A*np.exp(-(x-mu)**2/(2.*sigma**2))

def pointcor(north, south, east, west, cen, hpbw, dirname):
    """
    Given the power measured at the half-power points of the beam,
    calculate the correction factor for the source amplitude.
    The current implementation calculates the North-South and E-W 
    beams independently using a 1-D gaussian.
    We keep the width of the beam fixed during the fit.
    
    Inputs:
        north: Peak power measured at half-power point North 
        south: Peak power measured at half-power point South
        east: Peak power measured at half-power point East 
        west: Peak power measured at half-power point West
        cen: Peak power measured on source
        hpbw: half-power beam-width of the telescope
        
    Returns:
        Corrective factor for peak amplitude
    
    To do: 
        -- 2D fit
        -- Uncertainty using T_sys
        -- Use more than one of the peaks in the spectrum (only for source without confusion)
        to calculate the pointing correction. 
    """
    global hp
    hp = hpbw
    #hp = hpbw
    #global hp
     
    hhpbw = hpbw/2
    x = [-hhpbw, 0, +hhpbw]             
    p0 = [cen, 0.001]
   
    ns = [south, cen, north]
    ns_coeff, ns_var_matrix = curve_fit(gaussf, x, ns, p0)
    print(*ns_coeff)
    smooth = np.linspace(-4*hhpbw, 4*hhpbw, 100)
    ns_fits = gaussf(smooth, *ns_coeff)
    
    
    ew = [west, cen, east]
    ew_coeff, ew_var_matrix = curve_fit(gaussf, x, ew, p0)
    print(ew_coeff)
    ew_fits = gaussf(smooth, *ew_coeff)
    
       #print(*ew_coeff)
       #ew_fits = ew_fits*hpbw

    fig = plt.figure(figsize=[8,3])
    #plt.ion()
    ax = plt.subplot(121)
    ax.set_title("Pointing correction factor: %f " % (np.exp(np.log(2) * (ns_coeff[1]**2 + ew_coeff[1]**2) / hhpbw**2)))
    plt.plot(x, ns, 'bo')
    plt.plot(smooth, ns_fits, color='b')
    plt.axis('tight')
    plt.vlines(ns_coeff[1]+hhpbw, 0, cen, linestyle='dotted')
    plt.vlines(ns_coeff[1], 0, cen, linestyle='dotted')
    plt.vlines(ns_coeff[1]-hhpbw, 0, cen, linestyle='dotted')
    plt.title('North-South pointing offset '+str(round(ns_coeff[1],3)) +' deg')
    ax = plt.subplot(122)
    plt.plot(x, ew, 'ro')
    plt.plot(smooth, ew_fits, color='r')
    plt.axis('tight')
    plt.vlines(ew_coeff[1]+hhpbw, 0, cen, linestyle='dotted')
    plt.vlines(ew_coeff[1], 0, cen, linestyle='dotted')
    plt.vlines(ew_coeff[1]-hhpbw, 0, cen, linestyle='dotted')
    plt.title('East-West pointing offset '+str(round(ew_coeff[1],3)) +' deg')
    plt.savefig("../plots/Point_Offset_for_%s.pdf" % dirname[0:8], bbox_inches='tight')
    #plt.draw()
    #plt.pause(0.001)
    #time.sleep(2)
    plt.close()
    return np.exp(np.log(2) * (ns_coeff[1]**2 + ew_coeff[1]**2) / hhpbw**2), round(ns_coeff[1],3), round(ew_coeff[1],3)
    

