#--------------------------------------------------------------------------------------------------#
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

import numpy as np
import matplotlib.pyplot as plt
import os
import pickle
import time


def load_file(filename):
    """
    Open fits file, load spectra and extract information
    relevant to reductions.
    Returns a dictionary object.
    """
    hdulist = pyfits.open(filename)
    
    if hdulist[3].header['TCAL1']:
           #print(hdulist[3].header['TCAL1'])        
           hdulist[3].header['TSYS1'] = hdulist[3].header['TCAL1']
           hdulist[3].header['TSYSERR1'] = hdulist[3].header['TCALSIG1']
           hdulist[3].header['TSYS2'] = hdulist[3].header['TCAL2']
           hdulist[3].header['TSYSERR2'] = hdulist[3].header['TCALSIG2']
    
    if not hdulist[0].header['RESTFREQ']:
    
           hdulist[0].header['RESTFREQ'] = hdulist[2].header['CENTFREQ']
           hdulist[0].header['CENTFREQ'] = hdulist[2].header['CENTFREQ'] 
           #hdulist[0].header['RESTFREQ'] = hdulist[3].header['CENTFREQ']
    
    
    spectrum = {'Vlsr' : hdulist[2].data['Vlsr'],
                'LCP'  : hdulist[2].data['Polstate1'],
                'RCP'  : hdulist[2].data['Polstate4'],
                'units' : hdulist[2].header['TUNIT2'],
                'pointing' : hdulist[0].header['SPPOINT'],
                'position' : hdulist[2].header['POSITION'], 
                'HPBW' : hdulist[1].header['HPBW'],
                'date' : hdulist[0].header['DATE'],
                'object' : hdulist[0].header['OBJECT'],
                'longitude' : hdulist[0].header['LONGITUD'],
                'latitude' : hdulist[0].header['LATITUDE'],
                'Tamb'     : hdulist[0].header['TAMBIENT'],
                'Humid'    : hdulist[0].header['HUMIDITY'],
                'Focus' : hdulist[0].header['FOCUS'],
                'equinox' : hdulist[0].header['EQUINOX'],
                'bw' : hdulist[0].header['SPBW'],
                'nchan' : hdulist[0].header['SPCHAN'],
                't_int' : hdulist[0].header['SPTIME'],
                'fs_offset' : hdulist[0].header['SPFS'],
                'spVlsr' : hdulist[0].header['SPVLSR'],
                'restfreq' : hdulist[0].header['RESTFREQ'],
                'centrefreq' : hdulist[2].header['CENTFREQ'], 
                'Tsys_lcp' : hdulist[3].header['TSYS1'],
                'DTsys_lcp' : hdulist[3].header['TSYSERR1'],
                'Tsys_rcp' : hdulist[3].header['TSYS2'],
                'DTsys_rcp': hdulist[3].header['TSYSERR2'],
                'Cal1_lcp':  hdulist[3].data['Count1'],
                'Cal2_rcp':  hdulist[3].data['Count2'],
                'mjd_date': hdulist[3].data['MJD'],
                'HZPERK1':   hdulist[3].header['HZPERK1'],
                'HZKERR1':   hdulist[3].header['HZKERR1'],
                'HZPERK2':   hdulist[3].header['HZPERK2'],
                'HZPERR2':   hdulist[3].header['HZKERR2']}
                
                
        
    return spectrum
    hdulist.close()