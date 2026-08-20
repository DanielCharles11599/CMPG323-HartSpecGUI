#--------------------------------------------------------------------------------#
# Imports

from astropy.io import fits as pyfits
from astropy.io import ascii
from astropy.time import Time
from os import path
from astropy.time import Time
from scipy.optimize import curve_fit
from platform import python_version
from astropy.io import fits as pyfits
from scipy.stats import chisquare
from astropy.modeling import models
from astropy import units as u
#from specutils.spectra import Spectrum1D
#from specutils.fitting import fit_lines

import numpy as np
import math
import matplotlib.pyplot as plt
import os
import logging
import pickle
import time
import load_file as lf
import Stats_manager as St
import Pols as PL

def rms_stn(Amp, Vlsr, mask, mask3, vll, vrl, peak_vel, dirname, source, time):
    """
    Input: Amplitude spectrum, the velocity spectrum, masks for the baseline sections 
    and the velocity and the peak of the signal (peak_vel).
    
    The function takes the Amplitude spectrum and velocity spectrum together with the masks to 
    calculate the rms noise from the baseline sections, and then shows the baseline sections together 
    with +-rms on the plot. It also gives the maximum amplitude of the spectrum in the legend of the plot. 
    A pdf is then written of each observation. 
    
     
    
    """
    
        
        
    #print (max(Amp))
    noise = np.ma.array(Amp, mask = mask)
    rms = np.sqrt(np.ma.mean(noise**2))
    
    rms2, noise2, mask2 = St.Add_Remove_feature(Amp, Vlsr, mask, mask3, vll, vrl)
    
    #print('The measured rms noise is %0.2f Jy'%rms)
    plt.figure(figsize=[10,10])
    #plt.ion()
    ax = plt.subplot(111)
    #plt.plot(Vlsr, Amp)
    plt.plot(Vlsr, Amp, color='b', label="Max = %5.2f Jy" % max(Amp[np.where(mask3==0)]))
    plt.xlabel('V_lsr (km/s)')
    plt.ylabel('Flux density (Jy)')
    plt.title('Final spectrum for %s at %s' % (source, time))
    plt.axis('tight')
    #plt.ylim(-20,30)
    plt.plot(Vlsr, noise2, color='r')
    ax.axhline(-rms2, color='r', linestyle=':', label="RMS = %0.2f Jy" % rms2)
    ax.axhline(rms2, color='r', linestyle=':')
    plt.legend()
    #plt.savefig("../plots/Final_Spec_JY_%s.pdf" % dirname[0:8], bbox_inches='tight')
    plt.draw()
    plt.pause(0.001)
    plt.savefig("../plots/Final_Spec_JY_%s.pdf" % dirname[0:8], bbox_inches='tight')
    
    #plt.show()
    #time.sleep(5)
    #plt.close()
    
    #plt.show()
    
    
    return rms2, max(Amp[np.where(mask3==0)])
    
def Sig_point(Amp1, Amp2, Amp3, Amp4, Amp5, Vlsr, mask, peak_vel):
    
    """
    
    This function takes the amplitude spectra of all 5 the pointings, the mask of the baseline sections 
    and the peak velocity as input. The rms noise of each of the pointings are calculated and based on the 
    rms noise, it is decided if pointing correction will be done. The result is based on whether each of peaks 
    of the signal is at least 3-sigma above the rms noise level. If the rms noise of all 5 pointings are above the 3-sigma level, 
    the pointing correction is applied, otherwise if even one of the pointings are not strong enough, the pointing correction 
    defaults to a value of 1. 
    
    """
    print (peak_vel)    
    print (max(Amp1), max(Amp1[Vlsr==peak_vel]))
    
    noise = np.ma.array(Amp1, mask = mask)
    rms = np.sqrt(np.ma.mean(noise**2))
    noise2 = np.ma.array(Amp2, mask = mask)
    rms2 = np.sqrt(np.ma.mean(noise2**2))
    noise3 = np.ma.array(Amp3, mask = mask)
    rms3 = np.sqrt(np.ma.mean(noise3**2))
    noise4 = np.ma.array(Amp4, mask = mask)
    rms4 = np.sqrt(np.ma.mean(noise4**2))
    noise5 = np.ma.array(Amp5, mask = mask)
    rms5 = np.sqrt(np.ma.mean(noise5**2))
    pc_f = 1
    G_ahead=""    
    if (max(Amp1[Vlsr==peak_vel])/rms)>=2.5 and (max(Amp2[Vlsr==peak_vel])/rms2)>=2.5 and (max(Amp3[Vlsr==peak_vel])/rms3)>=2.5 and (max(Amp4[Vlsr==peak_vel])/rms4)>=2.5 and (max(Amp5[Vlsr==peak_vel])/rms5)>=2.5:
        print("Pointing corrections can be done")
        logging.info("Pointing corrections can be done")
        G_ahead = "Yes"
    
    #elif (max(Amp1[Vlsr==peak_vel])/rms)<2.5 and (max(Amp2[Vlsr==peak_vel])/rms)>2.5:
   
    #    pc_f = (math.log(max(Amp5))-math.log(max(Amp2))-math.log(2))**2/(4*math.log(2))
        #pc   = np.exp(pc_f)
    #    print("Pointing corrections can be done")
    #    logging.info("Pointing corrections can be done")
    #    G_ahead = "Half"
        
    #elif (max(Amp1[Vlsr==peak_vel])/rms)>2.5 and (max(Amp2[Vlsr==peak_vel])/rms)<2.5:
    
    #    pc_f = (math.log(max(Amp1))-math.log(max(Amp5))+math.log(2))**2/(4*math.log(2))
        #pc   = np.exp(pc_f)
    #    print("Pointing corrections can be done")
    #    logging.info("Pointing corrections can be done")
    #    G_ahead = "Half"
          
    #elif (max(Amp3[Vlsr==peak_vel])/rms)<2.5 and (max(Amp4[Vlsr==peak_vel])/rms)>2.5:
    
    #    pc_f = (math.log(max(Amp5))-math.log(max(Amp4))-math.log(2))**2/(4*math.log(2))
        #pc   = np.exp(pc_f)
    #    print("Pointing corrections can be done")
    #    logging.info("Pointing corrections can be done")
    #    G_ahead = "Half"
        
    #elif (max(Amp3[Vlsr==peak_vel])/rms)>2.5 and (max(Amp4[Vlsr==peak_vel])/rms)<2.5:
       
    #    pc_f = (math.log(max(Amp3))-math.log(max(Amp5))+math.log(2))**2/(4*math.log(2))
        #pc   = np.exp(pc_f)
    #    print("Pointing corrections can be done")
    #    logging.info("Pointing corrections can be done")
    #    G_ahead = "Half"
        
    elif (max(Amp1[Vlsr==peak_vel])/rms)<2.5 and (max(Amp2[Vlsr==peak_vel])/rms2)<2.5 and (max(Amp3[Vlsr==peak_vel])/rms3)<2.5 and (max(Amp4[Vlsr==peak_vel])/rms4)<2.5 and (max(Amp5[Vlsr==peak_vel])/rms5)<2.5:
       
        print("Pointing corrections can not be done")
        logging.info("Pointing corrections can not be done")
        G_ahead = "No"
        #pc_f = 1
    
    return G_ahead



    
def chi_S(bf1, bf2, bf3, bf4, bf5, bf6, Vlsr, Amp, Amp2, vll, vrl, mask, mask3):
    
    """
    Input: The fits of the polynomials for order, 3, 4, and 5 to both the LCP and RCP, the velocity spectrum, 
    the lower left (vll), and the upper right (vrl) velocities of the baseline spectrum, and the two masks for the baseline sections.
    The masks together with the polynomial fits are used to establish, which of the polynomial fits, fits the best to each polarization. 
    For each polarization, each polynomial fit is used to determine a least squares fit, and the combination of polarization and 
    order of polynomial which results in the smallest value for the least squares approach are used as the best baseline fit polynomial. 
    """
    
    
    chpl1 = 0
    chpl2 = 0
    chpl3 = 0
    chpr1 = 0
    chpr2 = 0
    chpr3 = 0
        
    for r in range(0, len(mask)-1, 1):
        if Vlsr[r]<=vll and Vlsr[r+1]>=vll:
            vl = r

        if Vlsr[r]<=vrl and Vlsr[r+1]>=vrl and vrl<Vlsr[len(mask3)-1]:
            vr = r

        if Vlsr[len(mask)-1]<vrl:
            vr = len(mask3)-2
    
    for e in range(vl, vr, 1):
        #print(e)
        if mask[e]==0:
            
            chpl1 += ((Amp[e] - bf1[e])**2)/bf1[e]
            chpl2 +=  ((Amp[e] - bf2[e])**2)/bf2[e]
            chpl3 +=  ((Amp[e] - bf3[e])**2)/bf3[e]
            chpr1 += ((Amp2[e] - bf4[e])**2)/bf4[e]
            chpr2 +=  ((Amp2[e] - bf5[e])**2)/bf5[e]
            chpr3 +=  ((Amp2[e] - bf6[e])**2)/bf6[e]

    Vall =[chpl1, chpl2, chpl3]
    Valr =[chpr1, chpr2, chpr3]
    Varl = ["chpl1", "chpl2", "chlp3"]
    Varr = ["chpr1", "chpr2", "chpr3"]
    VarO1 = [3, 4, 5]
    VarO2 = [3, 4, 5]
    #print(Val)
    n = len(Vall)
    for i in range(n):

        already_sorted = True

        for j in range(n - i - 1):

            if np.abs(Vall[j]) > np.abs(Vall[j + 1]):

                Vall[j], Vall[j + 1] = Vall[j + 1], Vall[j]
                Varl[j], Varl[j + 1] = Varl[j + 1], Varl[j]
                VarO1[j], VarO1[j + 1] = VarO1[j + 1], VarO1[j]
                already_sorted = False
                
            if np.abs(Valr[j]) > np.abs(Valr[j + 1]):

                Valr[j], Valr[j + 1] = Valr[j + 1], Valr[j]
                Varr[j], Varr[j + 1] = Varr[j + 1], Varr[j]
                VarO2[j], VarO2[j + 1] = VarO2[j + 1], VarO2[j]
                already_sorted = False

        if already_sorted:

            break
    
    if VarO1[0]==3:
        Ord=3
    elif VarO1[0]==4:
        Ord=4
    elif VarO1[0]==5:
        Ord=5
    
    if VarO2[0]==3:
        Ord2 = 3
    elif VarO2[0]==4:
        Ord2 = 4
    elif VarO2[0]==5:
        Ord2 = 5
    
            
    return Ord, Ord2 
    

def Add_Remove_feature(Amp, Vlsr, mask, mask3, vll, vrl):
    
    """
    Input: Amplitude, Velocity and masks and lower left and upper right value for the baseline sections. 
    Anywhere inbetween the lower left and upper right velocity values, it is tested if a new signal appeared 
    out of the baseline sections, and vice versa if any signal have disappeared and that the signal has 
    dropped below a 3 sigma detection limit. In the case, that a new signal have appeared in the baseline 
    selected part of the spectrum, the mask will be changed to exclude those channels from the baseline 
    baseline mask, and becomes part of signal part of the mask.
     
    """
    
    
    ns = np.ma.array(Amp, mask = mask)
    rms   = np.sqrt(np.ma.mean(ns**2))
    for r in range(0, len(mask)-1, 1):
        if Vlsr[r]<=vll and Vlsr[r+1]>=vll:
            vl = r
        
        if Vlsr[r]<=vrl and Vlsr[r+1]>=vrl and vrl<Vlsr[len(mask3)-1]:
            vr = r
            
        if Vlsr[len(mask)-1]<vrl:
            vr = len(mask3)-2
    
    #print(Vlsr[np.where(Vlsr==vll)])
    
    for e in range(vl, vr, 1):
        #print(e)
        if mask[e]==0 and np.abs(Amp[e])>=2.5*rms:
            #print(mask[e])
            mask[e]=1 
            #print(e)
            #print("NEW FEATURE HAVE APPEARED FROM THE BACKGROUND AT %f km/s" %Vlsr[e])
            logging.warning("NEW FEATURE HAVE APPEARED FROM THE BACKGROUND AT %f km/s" %Vlsr[e])
        
        elif mask3[e]==1 and np.abs(Amp[e])<=1.2*rms:
        
            mask[e]=0
            #print("FEATURE HAVE DISSAPPEARED AT %f km/s" %Vlsr[e])  
            logging.warning("FEATURE HAVE DISSAPPEARED AT %f km/s" %Vlsr[e])  
                
    noise2 = np.ma.array(Amp, mask=mask)
    rms2   = np.sqrt(np.ma.mean(noise2**2))
    
    for e in range(vl, vr, 1):
        #print(e)
        if mask[e]==0 and np.abs(Amp[e])>=2.5*rms:
            #print(mask[e])
            mask[e]=1 
            #print(e)
            #print("NEW FEATURE HAVE APPEARED FROM THE BACKGROUND AT %f km/s" %Vlsr[e])
            logging.warning("NEW FEATURE HAVE APPEARED FROM THE BACKGROUND AT %f km/s" %Vlsr[e])
        
        elif mask3[e]==1 and np.abs(Amp[e])<=1.2*rms:
        
            mask[e]=0
            #print("FEATURE HAVE DISSAPPEARED AT %f km/s" %Vlsr[e])  
            logging.warning("FEATURE HAVE DISSAPPEARED AT %f km/s" %Vlsr[e])  
    
    noise3 = np.ma.array(Amp, mask=mask)
    rms3   = np.sqrt(np.ma.mean(noise3**2))
    
    
    return rms3, noise3, mask
            
    
def Yfraction(Obs_time):
    
    
    doY = Obs_time[5:]
    #print(doY)
    Yr  = Obs_time[0:4]
    YR  = float(Yr)
    DOY = int(float(doY))
    
    if (YR/4)!=0:
    
        Dy = 365.0
    
    elif (YR/4)==0:
        
        Dy = 366.0
        
    
    Yearly = YR + DOY/Dy
    #print(Yearly)
    return Yearly
    


def Except_handle(files):
   
    for file in files:
        hdul    =pyfits.open(file)
        pos     = str(hdul[2].header['POSITION'])
        TS1     = float(hdul[3].header['TSYS1'])
        TS2     = float(hdul[3].header['TSYS2'])
           
        if TS1 > 0 and TS2 > 0:
        
           print("The system temperatures of %s at position %s has values of %f K and %f K. " % (files, pos, TS1, TS2))
           
        elif (TS1 < 0 or TS2 < 0) or (TS1 == '' or TS2 == ''):
           
           print("Something went wrong with the Meta-data and the system temperature readings %f and %f for %s in %s is faulty." % (TS1, TS2, files, pos))
           
    Test = input("Was there any observing files that was faulty?")
        
         
              
                               
