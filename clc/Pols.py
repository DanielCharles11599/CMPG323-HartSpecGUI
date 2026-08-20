#--------------------------------------------------------------------------------------#
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
from scipy.signal import savgol_filter

import numpy as np
import matplotlib.pyplot as plt
import os
import pickle
import time


def ave_pols(spec):
    """
    Average RCP and LCP pointing spectra and save in new data column.
    Return enhanced spectrum object.
    """
    spec['ave_pol'] = np.mean(np.vstack([spec['RCP'],spec['LCP']]), axis=0)
    return spec

def add_pols(spec):
    """
    Add RCP and LCP to get total intensity - Stokes I
    Return enhanced spectrum object.
    """
    spec['I'] = spec['RCP'] + spec['LCP']
    spec['I'] = savgol_filter(spec['I'], 7, 3)
    return spec
    
def ave_spec(spectra):
    """
    Average a list of spectra in time using a weighting according to integration time.
    Return a new spectrum.
    """
    mjd_list = list()
    lcp_list = list()
    rcp_list = list()
    t_int_list = list()
    spec1 = spectra[0]
    for spec in spectra:
        mjd_list.append(Time(spec['date'], scale='utc', format='isot').mjd)
        lcp_list.append(spec['LCP'])
        rcp_list.append(spec['RCP'])
        t_int_list.append(spec['t_int'])
    
    mjd_list = np.array(mjd_list)
    lcp_list = np.array(lcp_list)
    rcp_list = np.array(rcp_list)
    t_int_list = np.array(t_int_list)
    ave_lcp = np.average(np.vstack(lcp_list),axis=0, weights=t_int_list)
    ave_rcp = np.average(np.vstack(rcp_list),axis=0, weights=t_int_list)
    mid_time = Time(np.mean(mjd_list), format='mjd').iso
    ave_lcp2 = savgol_filter(ave_lcp, 7, 3)
    ave_rcp2 = savgol_filter(ave_rcp, 7, 3)
    #print mid_time
    #construct new spectrum
    ave_spec = {'object' : spec1['object'],
                'longitude' : spec1['longitude'],
                'latitude' : spec1['latitude'],
                'equinox' : spec1['equinox'],
                't_int' : np.sum(t_int_list),
                'HPBW' : spec1['HPBW'],
                'date' : mid_time,    
                'Vlsr' : spec1['Vlsr'],
                'Cal1_lcp': spec1['Cal1_lcp'],
                'Cal2_rcp': spec1['Cal2_rcp'],
                'mjd_date': spec1['mjd_date'],
                'LCP' : ave_lcp2,
                'RCP' : ave_rcp2}
    return ave_spec