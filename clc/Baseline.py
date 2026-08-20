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

def freq_switch(spec1, spec2):
    """
    Correct for bandpass response using frequency-switching and
    return spectra over common velocity range.
    Inputs: 
    spec1 : first observation of frequency-switched pair
    spec2 : second observation of frequency-switched pair
    Returns:
    new_spec1: bandpass-corrected frequency range
    new_spec2: bandpass-corrected frequency range
    
    """
    #subtract reference spectrum from signal
    
    
    lcp1 = spec1['LCP'] - spec2['LCP']
    lcp2 = spec2['LCP'] - spec1['LCP']
    rcp1 = spec1['RCP'] - spec2['RCP']
    rcp2 = spec2['RCP'] - spec1['RCP']
        
    #find the indices of the common velocity channels for each spectrum
    spec1_common = np.nonzero(np.in1d(spec1['Vlsr'], spec2['Vlsr']))
    spec2_common = np.nonzero(np.in1d(spec2['Vlsr'], spec1['Vlsr']))
    
    plt.plot(spec1['Vlsr'], spec1['LCP'])
    plt.plot(spec2['Vlsr'], spec2['LCP'])
    plt.plot(spec1['Vlsr'], spec1['RCP'])
    plt.plot(spec2['Vlsr'], spec2['RCP'])
    
    plt.xlabel("V$_{lsr}$ (km/s)", fontsize=20)
    plt.ylabel("T$_{sys}$ (K)", fontsize=20)
    #plt.draw()
    #plt.pause(0.001)
    plt.savefig("../plots/Bandpass_Example_FS.pdf", bbox_inches = 'tight')
    
    
    #time.sleep(5)
    
    
    #plt.savefig("../plots/Bandpass_Example_FS.pdf", bbox_inches='tight')
    #plt.show()
    
    #make a copy of the input spectra to preserve the header information
    new_spec1 = spec1.copy()
    new_spec2 = spec2.copy()
    
    #insert the new spectra into the copies
    new_spec1['Vlsr'] = spec1['Vlsr'][spec1_common]
    new_spec1['LCP'] = lcp1[spec1_common]
    new_spec1['RCP'] = rcp1[spec1_common]
    
    new_spec2['Vlsr'] = spec2['Vlsr'][spec2_common]
    new_spec2['LCP'] = lcp2[spec2_common]
    new_spec2['RCP'] = rcp2[spec2_common]

    
    return new_spec1, new_spec2
    

def pos_switch(spec1, spec2):
    """
    Correct for bandpass response using position-switching and
    return spectra over common velocity range.
    Inputs: 
    spec1 : On-source observation of position-switched pair
    spec2 : Off-source observation of position-switched pair
    Returns:
    new_spec: bandpass-corrected frequency range
    
    
    """
    #subtract reference spectrum from signal
    new_spec = spec1.copy()
    new_spec['LCP'] = spec1['LCP'] - spec2['LCP']
    new_spec['RCP'] = spec1['RCP'] - spec2['RCP']
    
    #plt.plot(spec1['Vlsr'], spec1['LCP'])
    #plt.plot(spec2['Vlsr'], spec2['LCP'])
    #plt.xlabel("V$_{lsr}$ (km/s)", fontsize=20)
    #plt.ylabel("T$_{sys}$ (K)", fontsize=20)
    #plt.draw()
    #plt.pause(0.001)
    plt.savefig("../plots/Bandpass_Example_PS.pdf", bbox_inches = 'tight')
    
    #time.sleep(2)
    
    #plt.savefig("../plots/Bandpass_Example_PS.pdf", bbox_inches = 'tight')
    #plt.show()
    
    return new_spec