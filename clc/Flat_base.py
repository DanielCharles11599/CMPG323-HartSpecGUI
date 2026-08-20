#----------------------------------------------------------------------------------#
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
from scipy.interpolate import CubicSpline
from scipy.interpolate import UnivariateSpline

import numpy as np
import matplotlib.pyplot as plt
import os
import pickle
import time
import Stats_manager as St

def flatten_baseline(Vlsr, Amp, Amp2, vll, vrl, mask, mask2):
    """
    Remove residual baseline variation after frequency- or position-switching.
    Inputs:
        Vlsr: array of velocity values
        Amp: array of intensity as a function of velocity
        mask, mask2: array element with 1's where line emission is and the edges, and 0's 
        for the rest of the mask where the baseline is fitted to. The fits are done for 3 
        different orders of the polynomial and the best one is used to flatten the baseline.
                
    Returns: Corrected amplitude
    
    
    """
    #mask = np.ones(len(Amp))
   
    
    #for y in range(0,len(llim)):
    #    mask[np.where(np.logical_and(Vlsr>=llim[y], Vlsr<=rlim[y]))] = 0
        
    
    vel_mask = np.ma.array(Vlsr, mask = mask)
    amp_mask = np.ma.array(Amp, mask = mask)
    
    vel_mask2 = np.ma.array(Vlsr, mask = mask2)
    amp_mask2 = np.ma.array(Amp2, mask = mask2)
    
    mask3 = np.ones(len(Vlsr))
    mask3[np.where(np.logical_and(Vlsr>=vll, Vlsr<=vrl))] = 0
    
    p1 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 3))
    p2 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 4))
    p3 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 5))
    p4 = np.poly1d(np.ma.polyfit(vel_mask2, amp_mask2, 3))
    p5 = np.poly1d(np.ma.polyfit(vel_mask2 ,amp_mask2, 4))
    p6 = np.poly1d(np.ma.polyfit(vel_mask2, amp_mask2, 5))
    
    bf1 = p1(Vlsr)
    bf2 = p2(Vlsr)
    bf3 = p3(Vlsr)
    bf4 = p4(Vlsr)
    bf5 = p5(Vlsr)
    bf6 = p6(Vlsr)
    
    Order, Order2 = St.chi_S(bf1, bf2, bf3, bf4, bf5, bf6, Vlsr, Amp, Amp2, vll, vrl, mask, mask3)
    
    print("The order of the best fit polynomial for LCP is: %i" %Order)
    print("The order of the best fit polynomial for RCP is: %i" %Order2)
    ###xm = Vlsr[np.where(mask==0)]
    ###ym = Amp[np.where(mask==0)]
    
    #p = InterpolatedUnivariateSpline(xm, ym, k=Order)
    p = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, Order))
    p2 = np.poly1d(np.ma.polyfit(vel_mask2, amp_mask2, Order2))
        
    basefit1 = p(Vlsr)
    basefit2 = p2(Vlsr)
    
    
    Amp  = Amp  - basefit1
    Amp2 = Amp2 - basefit2    

    #basefit = p(Vlsr)#Y_fitteddef flatten_baseline(Vlsr, Amp, llim, rlim, Order):
    
            
    #Amp = Amp - basefit
    
    return Amp, Amp2

def flatten_baseline2(Vlsr, Amp, Amp2, vll, vrl, mask, mask2):
    """
    Remove residual baseline variation after frequency- or position-switching.
    Inputs:
        Vlsr: array of velocity values
        Amp: array of intensity as a function of velocity
        llim, rlim: left and right limit of velocity ranges used for baseline subtraction
        mask: Boolean array representing the inclusion or exclusion of the velocity range into the baseline fit.
        
    The baseline ranges are chosen and masked and an n-order polynomial is used to flatten the baseline.
    
    Returns: Corrected amplitude
    
    """
        
    vel_mask = np.ma.array(Vlsr, mask = mask)
    amp_mask = np.ma.array(Amp, mask = mask)
    
    vel_mask2 = np.ma.array(Vlsr, mask = mask2)
    amp_mask2 = np.ma.array(Amp2, mask = mask2)
    
    mask3 = np.ones(len(Vlsr))
    mask3[np.where(np.logical_and(Vlsr>=vll, Vlsr<=vrl))] = 0
    
    p1 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 3))
    p2 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 4))
    p3 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 5))
    p4 = np.poly1d(np.ma.polyfit(vel_mask2, amp_mask2, 3))
    p5 = np.poly1d(np.ma.polyfit(vel_mask2 ,amp_mask2, 4))
    p6 = np.poly1d(np.ma.polyfit(vel_mask2, amp_mask2, 5))
    
    bf1 = p1(Vlsr)
    bf2 = p2(Vlsr)
    bf3 = p3(Vlsr)
    bf4 = p4(Vlsr)
    bf5 = p5(Vlsr)
    bf6 = p6(Vlsr)
    
    Order, Order2 = St.chi_S(bf1, bf2, bf3, bf4, bf5, bf6, Vlsr, Amp, Amp2, vll, vrl, mask, mask3)
    
    print("The order of the best fit polynomial for LCP is: %i" %Order)
    print("The order of the best fit polynomial for RCP is: %i" %Order2)
    ###xm = Vlsr[np.where(mask==0)]
    ###ym = Amp[np.where(mask==0)]
    
    #p = InterpolatedUnivariateSpline(xm, ym, k=Order)
    p = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, Order))
    p2 = np.poly1d(np.ma.polyfit(vel_mask2, amp_mask2, Order2))
        
    basefit1 = p(Vlsr)
    basefit2 = p2(Vlsr)
                
    Amp  = Amp  - basefit1
    Amp2 = Amp2 - basefit2    

    
           
    return Amp, Amp2
    
    
    
