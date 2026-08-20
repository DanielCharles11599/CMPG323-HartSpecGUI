from astropy.io import fits as pyfits
from astropy.io import ascii
from scipy.interpolate import UnivariateSpline, InterpolatedUnivariateSpline
from astropy.time import Time
from os import path
from astropy.time import Time
from scipy.optimize import curve_fit
from scipy.signal import find_peaks
from platform import python_version
from matplotlib.ticker import (MultipleLocator, FormatStrFormatter, AutoMinorLocator, ScalarFormatter)
from matplotlib import ticker
from astropy.modeling import models
from astropy import units as u
#from specutils.spectra import Spectrum1D
#from specutils.fitting import fit_lines
from scipy.stats import chisquare

import time
import os
import sys
import pickle
import logging
import numpy as np
import matplotlib.pyplot as plt
import Flat_base as Fb
import Pols as Pols
import Stats_manager as St


    
def Vlsr_p(av_spec, av_mask, vlsr_spec, vlsr_mask, RMS):

    peaks, _ = find_peaks(av_spec, height=10.0*RMS)
    
    
    vlsr_peaks = []
    #print(peaks)
    print(vlsr_spec[peaks])
    print(av_spec[peaks])
    for i in range(0, len(vlsr_spec[peaks]),1):
        vlsr_peaks.append(vlsr_spec[peaks[i]])
    #vlsr_peaks = vlsr_spec[peaks]
    fig = plt.figure()
    
    plt.plot(vlsr_spec, av_spec, '--r')
    plt.scatter(vlsr_spec[peaks], av_spec[peaks], color='blue', marker='+')
    plt.savefig("../plots/peaks_test_.pdf", bbox_inches="tight")
    plt.show()
    
    plt.close()
    
    return vlsr_peaks
    #A_max = max(av_mask)
    #A_idx = np.where(av_mask == peaks)
    #V_idx = vlsr_mask[A_idx]
    #Pk_vlsr = 
    
    
    #peaks, _ = find_peaks(x, height=0)
    
    #vll = llim[0]
    #vrl = rlim[-1]
    #print(vll, vrl)
    #mask3 = np.ones(len(sp['Vlsr']))
    #mask3[np.where(np.logical_and(sp['Vlsr']>=vll, sp['Vlsr']<=vrl))] = 0
    #Ind_mask = np.where(mask3==0)
    #print(Ind_mask)
    #A_mask = sp['ave_pol'][Ind_mask]
    #V_mask = sp['Vlsr'][Ind_mask]
    
    
    ##inDA = np.where(max(A_mask))
    #A_max = max(A_mask)
    #inDA = np.where(A_mask == A_max)
    #Vd = V_mask[inDA]
    #print("This is the Max of the signal: %5.5f                                                  #" % A_max)
    #print("This is the velocity at MAX signal %5.5f                                              #" % Vd)
    #logging.info("# This is the Max of the signal: %5.5f                                         #" % A_max)
    #logging.info("# This is the velocity at MAX signal %5.5f                                     #" % Vd)
    