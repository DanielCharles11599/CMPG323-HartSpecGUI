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
import Vlsr_point as VP

def Blocks(sp, h, Auto_Man, Full_YN):
    
    """
    The Blocks function firstly does a quick average polarisation calculation to get a better 
    signal-to-noise level. Then it displays the average spectrum. The average spectrum is then used to
    choose sections of the spectum (where there is no signal) to fit a polynomial to. 
    
    The first time you want to reduce spectra for a source, you will be asked to select how many baseline sections 
    there will be that will be used to fit the baseline polynomial to. Then you will proceed to input, first 
    the lower range for the first block then the upper range for the first block, and so you will continue 
    to the last block. 
    
    From here, there are two options, Manual or Automatic reduction of the spectra: 
    1. Manual
    Selecting the manual option, you will be able to select which order polynomial 
    fits the best, and then the software will continue to reduce the spectrum. 
    2. Automatic
    Selecting the automatic option, the software will then automatically reduce all 
    the spectra that is ready for reduction, and stop when it is finished.  
    
    The newest inclusion in the software, is that after you have chosen the baseline sections, the program 
    then proceeds to run through a script that tests for flagging parts of the spectrum at a 3-sigma level 
    of the noise to include/exclude parts of the sections. It then, uses a masked array, to know which part 
    of the spectrum is used for polynomial subtraction.  
     
    The selected baseline blocks are written to file to recall when new 
    observations are analysed. You are then prompted to select the best-fit before continuing. 
    """
    #fig = plt.plot(figsize = [20,10])
    #plt.xlim(59630, 59650)
    #plt.plot(sp['mjd_date'], sp['Cal1_lcp'])
    #plt.plot(sp['mjd_date'], sp['Cal2_rcp'])
    #print(sp['mjd_date'], sp['Cal1_lcp'])
    #time.sleep(10)
    #plt.show()


    #fig = plt.subplots(figsize=[10,5])
    # Calculate the average of both polarizations to get better S/N ratio



    


    sp_ave = Pols.ave_pols(sp)
    
    
    if (h==0):
    
        fig, ax = plt.subplots(figsize=[20,12])
        ax.plot(sp_ave['Vlsr'], sp_ave['ave_pol'])
        ax.set_xlabel('V_lsr (km/s)')
        ax.set_ylabel('Antenna temperature (K)')
        ax.xaxis.set_major_locator(MultipleLocator(5))
        ax.xaxis.set_minor_locator(MultipleLocator(1))
        ax.axis('tight')
        ax.set_title("Average Spectrum for %s " % sp['date'])
        plt.draw()
        plt.pause(0.001)
        plt.savefig("../plots/Ave_Spec_pol_%s.pdf"  % sp['date'][0:10], bbox_inches='tight')
        #raw_input("Press Enter to continue")
    #time.sleep(2)
    #plt.close()
    if Full_YN =="Yes":
        
        plt.draw()
        plt.pause(0.001)
        input("Press Enter to continue")
        plt.close()
             
    elif Full_YN =="No":
        
        a = 1
                  
        
    #initiating two lists for lower and upper ranges for the baseline blocks
    llim = list()
    rlim = list()
    
    i=0
    #print("# ======================================================================== #")
    #print("# The velocity of this Spectrum goes from \033[42m %3.3f \033[0m to \033[42m %3.3f \033[0m km/s " % (sp['Vlsr'][0], sp['Vlsr'][len(sp['Vlsr'])-1])) 
    #print("# ======================================================================== #")
    print("# The velocity of this Spectrum goes from %3.3f to %3.3f km/s " % (sp['Vlsr'][0], sp['Vlsr'][len(sp['Vlsr'])-1])) 
    print("# ======================================================================== #")
    logging.info("# The velocity of this Spectrum goes from %3.3f to %3.3f km/s " % (sp['Vlsr'][0], sp['Vlsr'][len(sp['Vlsr'])-1])) 
    logging.info("# ======================================================================== #")
    
    # Creating sub-strings to create filename for writing the baseline blocks to file.
    FR = str(sp['restfreq'])[0:5]
    OB = str(sp['object'])[0:4]
    Fn = str("../../Baseline_%s_%s.txt" % (FR, OB))
    
    #plt.close()
    # Tests if the file exists, if it doesn't you will be asked for input information for the spectrum.
    
    if not os.path.exists(Fn) and Auto_Man=="":
        os.system("rm Baseline_%s_%s.txt" % (FR, OB))
        Bline=open("%s" % Fn, "a+")
        #sys.stdin.read()
        count = input('How many baseline blocks do you want to choose? ')
        #count = sys.stdin
        num = int(count)
         
        for i in range(1,num+1):
        
            ll= input("Enter the low end of block %i:  " % i)
            rl= input("Enter the high end of block %i:  " % i)
            llim.append(float(ll))
            rlim.append(float(rl))
            
            try:
                
                Lrnge = str(ll)
                Rrnge = str(rl)
                rnge  = [Lrnge,Rrnge]
                Rs = '\n'
                R = '   '.join(rnge)
                Bline.write(R)
                Bline.write(Rs)
                
            except IOError:
                print('Empty or corrupt file: %s'%filename)
        Bline.close()
        #sys.stdin.close()
    
    elif (os.path.exists(Fn) and h==0 and Auto_Man==""):
        filename= "%s" % Fn
        Base_test = input('Do you want to make any changes to the baseline selection (Y/N)?  ')
        if (Base_test == "N" or Base_test == "No"):
        
            with open(filename, 'r') as f2:
                data=np.loadtxt(f2,dtype="float")
     
            llim = data[:,0]
            rlim = data[:,1]
            num = len(llim)
            
        elif (Base_test == "Y" or Base_test =="Yes"):
            os.system("rm Baseline_%s_%s.txt" % (FR, OB))
            Bline=open("%s" % Fn, "a+")
        #sys.stdin.read()
            count = input('How many baseline blocks do you want to choose? ')
        #count = sys.stdin
            num = int(count)
         
            for i in range(1,num+1):
        
               ll= input("Enter the low end of block %i:  " % i)
               rl= input("Enter the high end of block %i:  " % i)
               llim.append(float(ll))
               rlim.append(float(rl))
            
               try:
                
                   Lrnge = str(ll)
                   Rrnge = str(rl)
                   rnge  = [Lrnge,Rrnge]
                   Rs = '\n'
                   R = '   '.join(rnge)
                   Bline.write(R)
                   Bline.write(Rs)
                
               except IOError:
                   print('Empty or corrupt file: %s'%filename)
            Bline.close()
        
            
        #print(llim, rlim)
        
    # If the file does exists, it will be opened and the baseline blocks will be read from the file.  
    elif os.path.exists(Fn) and Full_YN=="No" or Full_YN=="":
        filename= "%s" % Fn
        #Testing = input('Is there a new feature in the baseline section?  ')
        
        
        with open(filename, 'r') as f2:
            data=np.loadtxt(f2,dtype="float")
     
        llim = data[:,0]
        rlim = data[:,1]
        num = len(llim)
        #print(llim, rlim)
        
    elif os.path.exists(Fn) and Full_YN=="Yes":
        os.system('rm Baseline_%s_%s.txt' % (FR, OB))
        Bline=open("%s" % Fn, "a+")
        
        
         #sys.stdin.read()
        count = input('How many baseline blocks do you want to choose? ')
        #count = sys.stdin
        num = int(count)
         
        for i in range(1,num+1):
        
            ll= input("Enter the low end of block %i:  " % i)
            rl= input("Enter the high end of block %i:  " % i)
            llim.append(float(ll))
            rlim.append(float(rl))
            
            try:
                
                Lrnge = str(ll)
                Rrnge = str(rl)
                rnge  = [Lrnge,Rrnge]
                Rs = '\n'
                R = '   '.join(rnge)
                Bline.write(R)
                Bline.write(Rs)
                
            except IOError:
                print('Empty or corrupt file: %s'%filename)
        Bline.close()
    #plt.close()    
        
    """
    For bad weather conditions or weak sources, sometimes the edges of the bandpass have spikes in them. After 
    band-pass correction have been done, the band-pass can still be higher than the signal itself. 
    For this reason, the edge of the band-pass is excluded from the baseline fit. This also enables choosing the 
    maximum of the signal for pointing corrections and not the band-pass edges
    """         
    Order = 0
    Order2= 0        
    vll = llim[0]
    vrl = rlim[-1]
    print(vll, vrl)
    mask3 = np.ones(len(sp['Vlsr']))
    mask3[np.where(np.logical_and(sp['Vlsr']>=vll, sp['Vlsr']<=vrl))] = 0
    Ind_mask = np.where(mask3==0)
    #print(Ind_mask)
    A_mask = sp['ave_pol'][Ind_mask]
    V_mask = sp['Vlsr'][Ind_mask]
    
    
    #inDA = np.where(max(A_mask))
    A_max = max(A_mask)
    inDA = np.where(A_mask == A_max)
    Vd = V_mask[inDA]
        
    #VP.Vlsr_p(sp['ave_pol'], A_mask, sp['Vlsr'], V_mask)
    print("This is the Max of the signal: %5.5f                                                  #" % A_max)
    print("This is the velocity at MAX signal %5.5f                                              #" % Vd)
    logging.info("# This is the Max of the signal: %5.5f                                         #" % A_max)
    logging.info("# This is the velocity at MAX signal %5.5f                                     #" % Vd)
    plt.close()
    
    fig, ((ax1, ax2, ax3), (ax4, ax5, ax6)) = plt.subplots(2, 3, figsize=[15,5])
    plt.ion()
    Amp = sp['LCP']
    Amp2 = sp['RCP']
    Vlsr= sp['Vlsr']
        #exfit = list()
    
              
    mask = np.ones(len(Amp))
    mask2 = np.ones(len(Amp2))
    for y in range(0,len(llim)):
        mask[np.where(np.logical_and(Vlsr>=llim[y], Vlsr<=rlim[y]))] = 0
        mask2[np.where(np.logical_and(Vlsr>=llim[y], Vlsr<=rlim[y]))] = 0
                
    vel_mask = np.ma.array(Vlsr, mask = mask)
    amp_mask = np.ma.array(Amp, mask = mask)
    vel_mask2 = np.ma.array(Vlsr, mask = mask2)
    amp_mask2 = np.ma.array(Amp2, mask = mask2)
    #print(mask)
    xm = Vlsr[np.where(mask==0)]
    ym = Amp[np.where(mask==0)]
    xm2 = Vlsr[np.where(mask2==0)]
    ym2 = Amp2[np.where(mask2==0)]
    
    # create the objects for order, 3, 4 and 5 polynomials and both polarizations. 
    p1 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 3))
    p2 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 4))
    p3 = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 5))
    p4 = np.poly1d(np.ma.polyfit(vel_mask2, amp_mask2, 3))
    p5 = np.poly1d(np.ma.polyfit(vel_mask2 ,amp_mask2, 4))
    p6 = np.poly1d(np.ma.polyfit(vel_mask2, amp_mask2, 5))
    
    #obtaining the fits for the abovementioned objects.
    bf1 = p1(Vlsr)
    bf2 = p2(Vlsr)
    bf3 = p3(Vlsr)
    bf4 = p4(Vlsr)
    bf5 = p5(Vlsr)
    bf6 = p6(Vlsr)
    
    if Full_YN =="Yes":
        
        ax1.plot(Vlsr, Amp, label="Order = 3")
        ax1.plot(vel_mask, amp_mask)
        ax1.plot(Vlsr, bf1)
        ax1.xaxis.set_major_locator(MultipleLocator(5))
        ax1.xaxis.set_minor_locator(MultipleLocator(1))

   
        ax2.plot(Vlsr, Amp, label = "Order = 4")
        ax2.plot(vel_mask, amp_mask)
        ax2.plot(Vlsr, bf2)
        #ax2.plot(Vlsr, basefit21, color='black')
        ax2.xaxis.set_major_locator(MultipleLocator(5))
        ax2.xaxis.set_minor_locator(MultipleLocator(1))
        ax2.set_title('Polynomial fits to the baselines of %s' % sp['object'])
        #ax2.plot(Vlsr, basefit22, color='b')
        ax3.plot(Vlsr, Amp, label = "Order = 5")
        ax3.plot(vel_mask, amp_mask)
        ax3.plot(Vlsr, bf3)
        #ax3.plot(Vlsr, basefit31, color='black')
        ax3.xaxis.set_major_locator(MultipleLocator(5))
        ax3.xaxis.set_minor_locator(MultipleLocator(1))

        #ax3.plot(Vlsr, basefit32, color='b')
        ax4.plot(Vlsr, Amp2, label = "Order = 3")
        ax4.plot(vel_mask2, amp_mask2)
        ax4.plot(Vlsr, bf4)
        #ax4.plot(Vlsr, basefit41, color='black')
        ax4.xaxis.set_major_locator(MultipleLocator(5))
        ax4.xaxis.set_minor_locator(MultipleLocator(1))

        #ax4.plot(Vlsr, basefit42, color='b')
        ax5.plot(Vlsr, Amp2, label= "Order = 4")
        ax5.plot(vel_mask2, amp_mask2)
        ax5.plot(Vlsr, bf5)
        #ax5.plot(Vlsr, basefit51, color='black')
        ax5.xaxis.set_major_locator(MultipleLocator(5))
        ax5.xaxis.set_minor_locator(MultipleLocator(1))

        #ax5.plot(Vlsr, basefit52, color='b')
        ax6.plot(Vlsr, Amp2, label = "Order = 5")
        ax6.plot(vel_mask2, amp_mask2)
        ax6.plot(Vlsr, bf6)
        #ax6.plot(Vlsr, basefit61, color='black')
        ax6.xaxis.set_major_locator(MultipleLocator(5))
        ax6.xaxis.set_minor_locator(MultipleLocator(1))

        ax1.set_ylabel(r"LCP Antenna temp (K)" )
        ax1.legend()
        ax2.legend()
        ax3.legend()
        ax4.legend()
        ax5.legend()
        ax6.legend()
        ax4.set_ylabel(r"RCP Antenna temp (K)" )
        ax4.set_xlabel(r"Vlsr (km/s)" )
        ax5.set_xlabel(r"Vlsr (km/s)" )
        ax6.set_xlabel(r"Vlsr (km/s)" )
        tt = Time(sp['date'], format='isot', scale='utc')
        tyd = tt.mjd
        #ax1.set_ylabel(r"Antenna temp (K)" )
        #plt.plot(new_spec1['Vlsr'], new_spec1['LCP'])
        # Save a file based on the MJD of the observation.
        plt.savefig("../plots/Bandpass_PLOrder_%5.0f.pdf" % tyd, bbox_inches='tight')
        plt.draw()
        plt.pause(0.001)
        
        OrD = input("Which order polynomial fits the best for LCP?  ")
        Order = OrD
        #Order = 4
        OrD2 = input("Which order polynomial fits the best for RCP?  ")
        Order2 = OrD2
        #Order2 = 4
    
        plt.close()
    
    elif Full_YN =="No" or Full_YN =="":
        
        # Using the fits, get the orders which best fits each polarization.
        Order, Order2 = St.chi_S(bf1, bf2, bf3, bf4, bf5, bf6, Vlsr, Amp, Amp2, vll, vrl, mask, mask3)    
    
    # Plot all 6 polynomial fits on a 3 x 2 grid, to see the goodness of fit.
        ax1.plot(Vlsr, Amp, label="Order = 3")
        ax1.plot(vel_mask, amp_mask)
        ax1.plot(Vlsr, bf1)
        ax1.xaxis.set_major_locator(MultipleLocator(5))
        ax1.xaxis.set_minor_locator(MultipleLocator(1))

   
        ax2.plot(Vlsr, Amp, label = "Order = 4")
        ax2.plot(vel_mask, amp_mask)
        ax2.plot(Vlsr, bf2)
    #ax2.plot(Vlsr, basefit21, color='black')
        ax2.xaxis.set_major_locator(MultipleLocator(5))
        ax2.xaxis.set_minor_locator(MultipleLocator(1))

    #ax2.plot(Vlsr, basefit22, color='b')
        ax3.plot(Vlsr, Amp, label = "Order = 5")
        ax3.plot(vel_mask, amp_mask)
        ax3.plot(Vlsr, bf3)
    #ax3.plot(Vlsr, basefit31, color='black')
        ax3.xaxis.set_major_locator(MultipleLocator(5))
        ax3.xaxis.set_minor_locator(MultipleLocator(1))

    #ax3.plot(Vlsr, basefit32, color='b')
        ax4.plot(Vlsr, Amp2, label = "Order = 3")
        ax4.plot(vel_mask2, amp_mask2)
        ax4.plot(Vlsr, bf4)
    #ax4.plot(Vlsr, basefit41, color='black')
        ax4.xaxis.set_major_locator(MultipleLocator(5))
        ax4.xaxis.set_minor_locator(MultipleLocator(1))

    #ax4.plot(Vlsr, basefit42, color='b')
        ax5.plot(Vlsr, Amp2, label= "Order = 4")
        ax5.plot(vel_mask2, amp_mask2)
        ax5.plot(Vlsr, bf5)
    #ax5.plot(Vlsr, basefit51, color='black')
        ax5.xaxis.set_major_locator(MultipleLocator(5))
        ax5.xaxis.set_minor_locator(MultipleLocator(1))

    #ax5.plot(Vlsr, basefit52, color='b')
        ax6.plot(Vlsr, Amp2, label = "Order = 5")
        ax6.plot(vel_mask2, amp_mask2)
        ax6.plot(Vlsr, bf6)
    #ax6.plot(Vlsr, basefit61, color='black')
        ax6.xaxis.set_major_locator(MultipleLocator(5))
        ax6.xaxis.set_minor_locator(MultipleLocator(1))

        ax1.set_ylabel(r"LCP Antenna temp (K)" )
        ax1.legend()
        ax2.legend()
        ax3.legend()
        ax4.legend()
        ax5.legend()
        ax6.legend()
        ax4.set_ylabel(r"RCP Antenna temp (K)" )
        ax4.set_xlabel(r"Vlsr (km/s)" )
        ax5.set_xlabel(r"Vlsr (km/s)" )
        ax6.set_xlabel(r"Vlsr (km/s)" )
        tt = Time(sp['date'], format='isot', scale='utc')
        tyd = tt.mjd
    #ax1.set_ylabel(r"Antenna temp (K)" )
    #plt.plot(new_spec1['Vlsr'], new_spec1['LCP'])
    # Save a file based on the MJD of the observation. Plotting only when it is not automated.
        plt.savefig("../plots/Bandpass_PLOrder_%5.0f.pdf" % tyd, bbox_inches='tight')
        #plt.draw()
        #plt.pause(0.001)
        #time.sleep(5)
        
    #plt.draw()
    #plt.pause(0.001)
    #time.sleep(5)
        #plt.close()
    
    #Quality = input("Does the polynomial fit the baseline well?")
    #if Quality=="Y":
    #OrD = input("Which order polynomial fits the best for LCP?  ")
    #Order = np.int(OrD)
    #Order = 4
    #OrD2 = input("Which order polynomial fits the best for RCP?  ")
    #Order2 = np.int(OrD2)
    #Order2 = 4
        
    print("The order of the best fit polynomial for LCP is: %i" % int(Order))
    print("The order of the best fit polynomial for RCP is: %i" % int(Order2))
           
    New_Amp1, New_Amp2 = Fb.flatten_baseline(sp['Vlsr'], sp['LCP'], sp['RCP'], vll, vrl, mask, mask2)
    #New_Amp2 = flatten_baseline(sp['Vlsr'], sp['RCP'], mask2, Order2)
    
    rms1, noise, mask = St.Add_Remove_feature(New_Amp1, Vlsr, mask, mask3, vll, vrl)
    rms2, noise2, mask2 = St.Add_Remove_feature(New_Amp2, Vlsr, mask2, mask3, vll, vrl)

    New_Amp3, New_Amp4 = Fb.flatten_baseline(sp['Vlsr'], sp['LCP'], sp['RCP'], vll, vrl, mask, mask2)
    
    Vd_new = VP.Vlsr_p(sp['ave_pol'], A_mask,  sp['Vlsr'], V_mask, rms2)
    
    #fig = plt.figure(figsize=[10,5])
    #plt.plot(sp['Vlsr'], New_Amp3)
    #plt.plot(sp['Vlsr'], noise)
    #plt.plot(sp['Vlsr'], New_Amp4)
    #plt.plot(sp['Vlsr'], noise2)
    #plt.xlabel('Vlsr km/s')
    #plt.ylabel('Antenna temperature (K)')
    #plt.show()
    
    #plt.plot(sp['Vlsr'], New_Amp3)
    #plt.plot(sp['Vlsr'], noise)
    #plt.plot(sp['Vlsr'], New_Amp4)
    #plt.plot(sp['Vlsr'], noise2)
    
    #plt.xlabel('Vlsr km/s')
    #plt.ylabel('Antenna temperature (K)')
    #plt.axis('tight')
    #plt.ion()
    #plt.draw()
    #plt.pause(0.001)
    #time.sleep(5)
    #plt.clf()
    #plt.close()
         
    return  mask, mask2, mask3, vll, vrl, Vd, Vd_new, int(num), int(Order), int(Order2)

    
    
