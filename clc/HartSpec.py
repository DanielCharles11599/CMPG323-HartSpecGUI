#!/usr/bin/env python3
# ================================================================================== #
# Project : HartRAO's 26 m Single-dish Spectroscopy data reduction analysis software #
# File    : HartSpec.py                                                              #
# Author  : S.P. van den Heever                                                     #
# Date    : 04/05/2021                                                               #
# Version : v1.02                                                                     #
# ================================================================================== #

# Library imports
# ---------------------------------------------------------------------------------- #

from astropy.io import fits as pyfits
from astropy.io import ascii
from astropy.time import Time
from os import path
from scipy.optimize import curve_fit
from platform import python_version
from astropy.modeling import models
from astropy import units as u
#from specutils.spectra import Spectrum1D
#from specutils.fitting import fit_lines
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from ipywidgets import interact, interactive, fixed, interact_manual
from IPython.display import display
from ipywidgets import IntSlider, Output
from functools import wraps
from glob import glob
from ipywidgets import IntSlider, VBox, HTML
from scipy.signal import savgol_filter
from matplotlib.ticker import (MultipleLocator, FormatStrFormatter,
                               AutoMinorLocator, ScalarFormatter)
from termcolor import colored
from colorama import Fore
from colorama import Style
from contextlib import redirect_stdout

import time
import numpy as np
import matplotlib.pyplot as plt
import os
import sys
import pickle
import shutil
import logging
#import info
#import ipywidgets as widgets
import threading
import asyncio
#import pyspeckit

# Function imports
# ---------------------------------------------------------------------------------- #
import load_file as lf
import plot_spec as plot_spec
import Baseline as Bl
import Flat_base as Fb
import fit_max as fm
import Spec_comp as Spec_comp
import Gaussf as Gaussf
import Point_cor as PC
import Pols as Pols
import Cal_point_cor as Cpc
import Cal_point_check as Cpch
import Blocks as BS
import Stats_manager as St
import Obs_Point_Full as OPF
import Calibrate_PSS_PWR as CPP
import File_Manage as FE
import Option as OPT
import Interact as ITA 
# Variable initiation
# ---------------------------------------------------------------------------------- #
llim = 0
rlim = 0
peak_vel = 0
peak_vels = 0
h=0
half_width = 3
Auto_Man = ""
Full_YN = ""
precip = 0.0

# Taking the command-line arguments and inputting it into variables.
#args = sys.argv
#Source    = args[1]
#Frequency = args[2]

Source, Frequency = ITA.interaction()

# Testing existence of file
if not os.path.exists('/data/'+Source+'/'+Frequency+'/%s_%s.log' % (Source, Frequency)):
    cwd = os.getcwd()
    work_dir = cwd+'/data/'+Source+'/'+Frequency+'/'
    os.chdir(work_dir)
    #sys.stdout = open('Log_file_%s_%s.txt' % (Source, Frequency), 'w')

elif os.path.exists('/data/'+Source+'/'+Frequency+'/%s_%s.log' % (Source, Frequency)):
    cwd = os.getcwd()
    work_dir = cwd+'/data/'+Source+'/'+Frequency+'/'
    os.chdir(work_dir)

# Initiate the logging of output to the log_file.
logging.basicConfig(filename='%s_%s.log' % (Source, Frequency),  level=logging.INFO)

# Sorting Observing directories for sequential read and Creating directories for Completed and Flagged data.
dirs = glob("*/")
DD = sorted(dirs)
 #DD.remove('Done/')
#DD.remove('Flagged/')
if 'Bad_data/' in DD:
    DD.remove('Bad_data/')
if 'Done/' in DD:
    DD.remove('Done/')
else:
    os.system("mkdir Done")
if 'plots/' in DD:
    DD.remove('plots/')
else:
    os.system("mkdir plots")

if 'Flagged/' in DD:
    DD.remove('Flagged/')
else:
    os.system("mkdir Flagged")
#if 'plots/' in DD:
#    DD.remove('plots/'

#else:
#    os.system("mkdir plots")

    """
    This is the main programme that connects all of the scripts into one package. It reads in all the directories
    with observations one-by-one. After entering each observing directory, it tests whether the observation
    was a complete observation set of 10 files; 6 pointing observations and 2 pairs of ON-source integrations, which consists
    of either a frequency-switched pair or a position-switched pair for reference subtraction.

    Other combinations of the observing files are a set of 8 observing files, with 6 pointing observations and only one
    pair of integration observations. Only 6 pointing observations (for strong sources or pointing checks), where the short
    on-source integration can be used as the on-source integration. Lastly, only On-source integration observations
    (either one or two pairs), where the pointing correction is simply set to 1. These options are divided into frequency-switched
    and position-switched to easily distinguish from the position "ON" or "OFF".

    Whether it is only pointing observations or one pair or two pairs, the average spectrum is then calculated and the "LCP" and
    "RCP", and "I" spectrum is written to file, together with statistics like, tsys_lcp, tsys-rcp, pointing correction, atmospheric
    correction, NW and EW pointing OFFsets, PSS_LCP, PSS_RCP, Elevation, Azimuth, and rms noise. All of this information is also
    written into a log-file.



    """

#Auto_Man = "Man"
SM_vel = input("Do you want to do multiple pointing checks? (Y/N): ")

# Start processing the observations 1-by-1.
for dirname in DD:
    os.chdir(work_dir+'/'+dirname)
    logging.info('Processing : %s' % (str(dirname[0:8])) )
    print('Processing : %s' %(dirname) )
    Obs_T = dirname[0:8]
    YFrac = St.Yfraction(Obs_T)
    os.system('rm observation_list.txt')
    if not os.path.exists('observation_list.txt'):
        os.system('ls *.fits > fits_list.txt')
        file_list = np.atleast_1d(np.loadtxt('fits_list.txt', dtype='str'))
        # Do tests to check if all the header information is in the files.
        #New_list = FE.File_err(file_list, Source, Frequency)
        with open('observation_list.txt', 'w') as f:
            for filename in file_list:

                try:
                    # Write the Filename, position and pointing into a file, to use for testing for pointing or ON/OFF source position.
                    hdulist = pyfits.open(filename)
                    posi    = str(hdulist[2].header['POSITION'])
                    point   = str(hdulist[0].header['SPPOINT'])
                    V1 = str(hdulist[2].data['Vlsr'][0])
                    r =[filename, posi, point, V1]
                    description = ' '.join(r)
                    r2 = '\n'
                    f.write(description)
                    f.write(r2)
                except IOError:
                    logging.warning('Empty or corrupt file: %s' %filename)
                    print('Empty or corrupt file: %s'%filename)
        os.system('rm fits_list.txt')

    file_list = np.loadtxt(fname ="observation_list.txt", delimiter=' ',
                           dtype={'names': ('filename', 'position', 'pointing', 'velocity'),
                           'formats': ('|S100','|S3','b', '|S8')} )

    decoder = np.vectorize(lambda x: x.decode('UTF-8'))
    file_list3 = decoder(file_list['filename'])
    file_list2 = decoder(file_list['position'])
    print(file_list)
    #time.sleep(2)
    #print (file_list2)
    #St.Except_handle(file_list)
    full_int_on = np.where(file_list['pointing']==0)[0]
    #print(full_int_on)
    spectra = list()
    file_list4 = list()
    file_list5 = list()
    file_list6 = list()
    # This if statement is employed for NH3 mapping observations, when the reference OFF-source observation was made before the ON-source observation.
    if file_list2[0]=='OFF':
        print(file_list3, file_list2)
        file_list4.append(file_list3[1])
        file_list4.append(file_list3[0])
        file_list5.append(file_list2[1])
        file_list5.append(file_list2[0])
        file_list3 = file_list4
        file_list2 = file_list5



    #if file_list2[0]!="HPN":

    #    for i in range(4,10,1):
    #        file_list5.append(file_list3[i])
    #        file_list4.append(file_list2[i])
    #        file_list6.append(file_list[i])
    #    for j in range(0,4,1):
    #        file_list5.append(file_list3[j])
    #        file_list4.append(file_list2[j])
    #        file_list6.append(file_list[j])

    #    file_list3 = file_list4
    #    file_list2 = file_list5
    #    file_list  = file_list6

    #print(file_list2)
    #print(file_list3)
    #time.sleep(5)
        
    num_full_pairs = int(len(full_int_on)/2)
    pointing_obs = np.where(file_list['pointing']==1)[0]
    num_pointing_obs = len(file_list['pointing'][np.where(file_list['pointing']==1)])
    #print (pointing_obs, num_pointing_obs)

    spectra = list()
    Elev_ang = 0
    ATcor = 0
    tsys_l = 0
    tsys_r = 0
    
    #PC_vels = str('PC_Vels_%s_%s.txt' % (OBJ, Freq))
    #PC=open("../%s" % PC_vels, "a+")
    
    
    #    f.write("\n")
    Vlsr_point = {}
    ONS = []
    OEW = []
    PCT = []
    
    
    
    if num_full_pairs!=0 and num_pointing_obs==6 and file_list2[full_int_on[1]]=='OFF':

        logging.info("# ==================================================================================== #")
        logging.info("# Starting to process Position-Switching observations with ON-source observations.     #")
        logging.info("# ==================================================================================== #")

        print("# ==================================================================================== #")
        print("# Starting to process Position-Switching observations with ON-source observations.     #")
        print("# ==================================================================================== #")
        on_ps1 = lf.load_file(file_list3[full_int_on[0]])
        on_ps2 = lf.load_file(file_list3[full_int_on[1]])
        plt.plot(on_ps1['mjd_date']-55000, on_ps1['Cal1_lcp']/1000000)
        plt.plot(on_ps1['mjd_date']-55000, on_ps1['Cal2_rcp']/1000000)
        plt.xlabel('MJD - 55000')
        plt.ylabel('System counts (10$^{6}$)')
        plt.title("Calibration signal for %s " % on_ps1['date'])
    
        plt.draw()
        plt.pause(0.001)
        
        plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_ps1['date'][0:10], bbox_inches='tight')
        #plt.show()
        #time.sleep(2)
        if Full_YN == "Yes":
            input("Press Enter to continue")
        #plt.show()
        #time.sleep(5)
        #plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_fs1['date'][0:10], bbox_inches='tight')
        #plt.show()
        plt.close()
        r = 0
        T_amb = on_ps1['Tamb']
        new_spec1  = Bl.pos_switch(on_ps1, on_ps2)
        Freq = str(new_spec1['restfreq'])[0:5]
        mask, mask2, mask3, vll, vrl , peak_vel, peak_vels, num, Order, Order2 = BS.Blocks(new_spec1, h, Auto_Man, Full_YN)
        
        if SM_vel=="Y":
            
            for k in range(0,len(peak_vels), 1):
            
                pc, NS_off, EW_off = Cpch.calculate_pointing_corr_pos(file_list, file_list2, file_list3, mask, mask2, peak_vels[k], half_width, vll, vrl, dirname, Full_YN)
                ONS.append(NS_off)
                OEW.append(EW_off)
                PCT.append(pc) 
            test_point = {'Time' : YFrac, 'Vlsr' : peak_vels, 'PCS': PCT,'OffNS': ONS, 'OffEW': OEW}
            
            #if h==0:
            Vlsr_point.update(test_point)
                
            #else:
                #current = test_point[r]
            #    for key, value in test_point.items():
            #        Vlsr_point[key].append(value)
                               
                
        else:
        
            pc, NS_off, EW_off = Cpc.calculate_pointing_corr_pos(file_list, file_list2, file_list3, mask, mask2, peak_vel, half_width, vll, vrl, dirname, Full_YN)
            
            
        print("# The Pointing correction calculations have been completed!!                           #")
        print("# ==================================================================================== #")
        print("# The Pointing correction factor is: %2.3f " % (pc) )
        print("# ==================================================================================== #")
        print("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
        print("# ==================================================================================== #")
        
        logging.info("# The Pointing correction calculations have been completed!!                           #")
        logging.info("# ==================================================================================== #")
        logging.info("# The Pointing correction factor is: %2.3f " % (pc) )
        logging.info("# ==================================================================================== #")
        logging.info("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
        logging.info("# ==================================================================================== #")

        spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip = OPF.reduce_point(file_list, file_list2, file_list3, mask, mask2, vll, vrl, Freq, spectra)
        spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip = OPF.full_point_obs(file_list, file_list2, file_list3, num_full_pairs, full_int_on, mask, mask2, vll, vrl, Freq, spectra)


    if num_full_pairs==0 and num_pointing_obs==6 and file_list2[5]=='OFF':
        print("# ==================================================================================== #")
        print("# Starting to process Position-Switching observations without ON-source observations.  #")
        print("# ==================================================================================== #")
        logging.info("# ==================================================================================== #")
        logging.info("# Starting to process Position-Switching observations without ON-source observations.  #")
        logging.info("# ==================================================================================== #")

        on_ps1 =lf.load_file(file_list3[4])
        on_ps2 = lf.load_file(file_list3[5])
        plt.plot(on_ps1['mjd_date']-55000, on_ps1['Cal1_lcp']/1000000)
        plt.plot(on_ps1['mjd_date']-55000, on_ps1['Cal2_rcp']/1000000)
        plt.xlabel('MJD - 55000')
        plt.ylabel('System counts  (10$^{6}$)')
        plt.title("Calibration signal for %s " % on_ps1['date'])
    
        plt.draw()
        plt.pause(0.001)
        plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_ps1['date'][0:10], bbox_inches='tight')
        #plt.show()
        #time.sleep(2)
        if Full_YN == "Yes":
            input("Press Enter to continue")
        
        #plt.show()
        #time.sleep(5)
        #plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_fs1['date'][0:10], bbox_inches='tight')
        #plt.show()
        plt.close()

        T_amb = on_ps1['Tamb']
        new_spec1 = Bl.pos_switch(on_ps1, on_ps2)
        Freq = str(new_spec1['restfreq'])[0:5]
        mask, mask2, mask3, vll, vrl, peak_vel, peak_vels, num, Order, Order2 = BS.Blocks(new_spec1, h, Auto_Man, Full_YN)
        #pc, NS_off, EW_off = Cpc.calculate_pointing_corr_pos(file_list, file_list2, file_list3, mask, mask2, peak_vel, half_width, vll, vrl, dirname, Full_YN)
        
        if SM_vel=="Y":
            
            for k in range(0,len(peak_vels), 1):
            
                pc, NS_off, EW_off = Cpch.calculate_pointing_corr_pos(file_list, file_list2, file_list3, mask, mask2, peak_vels[k], half_width, vll, vrl, dirname, Full_YN)
                ONS.append(NS_off)
                OEW.append(EW_off)
                PCT.append(pc) 
            test_point = {'Time' : YFrac, 'Vlsr' : peak_vels, 'PCS': PCT,'OffNS': ONS, 'OffEW': OEW}
            
            #if h==0:
            
            Vlsr_point.update(test_point)
            
            #else:
            
                #current = test_point[r]
            #    for key, value in test_point.items():
            #            Vlsr_point[key].append(value)
            #Vlsr_point.update(test_point)
                
        else:
        
            pc, NS_off, EW_off = Cpc.calculate_pointing_corr_pos(file_list, file_list2, file_list3, mask, mask2, peak_vel, half_width, vll, vrl, dirname, Full_YN)
            
                
        print("# The Pointing correction calculations have been completed!!                            #")
        print("# ===================================================================================== #")
        print("# The Pointing correction factor is: %2.3f " % (pc) )
        print("# ===================================================================================== #")
        print("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
        print("# ===================================================================================== #")
        logging.info("# The Pointing correction calculations have been completed!!                            #")
        logging.info("# ===================================================================================== #")
        logging.info("# The Pointing correction factor is: %2.3f " % (pc) )
        logging.info("# ===================================================================================== #")
        logging.info("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
        logging.info("# ===================================================================================== #")

        spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip = OPF.reduce_point(file_list, file_list2, file_list3, mask, mask2, vll, vrl, Freq, spectra)


    if num_full_pairs!=0 and num_pointing_obs==6 and file_list2[full_int_on[1]]=='ON':
        print("# ================================================================================== #")
        print("# Starting to process Frequency-Switching observations with ON-source observations.  #")
        print("# ================================================================================== #")
        logging.info("# ================================================================================== #")
        logging.info("# Starting to process Frequency-Switching observations with ON-source observations.  #")
        logging.info("# ================================================================================== #")

        on_fs1 = lf.load_file(file_list3[full_int_on[0]])
        on_fs2 = lf.load_file(file_list3[full_int_on[1]])
        plt.plot(on_fs1['mjd_date']-55000, on_fs1['Cal1_lcp']/1000000)
        plt.plot(on_fs1['mjd_date']-55000, on_fs1['Cal2_rcp']/1000000)
        plt.xlabel('MJD - 55000')
        plt.ylabel('System counts (10$^{6}$)')
        
        plt.title("Calibration signal for %s " % on_fs1['date'])
    
        plt.draw()
        plt.pause(0.001)
        plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_fs1['date'][0:10], bbox_inches='tight')
        #plt.show()
        #time.sleep(2)
        if Full_YN == "Yes":
            input("Press Enter to continue")
        
        #plt.show()
        #time.sleep(5)
        #plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_fs1['date'][0:10], bbox_inches='tight')
        #plt.show()
        plt.close()
        T_amb = on_fs1['Tamb']
        new_spec1, new_spec2 = Bl.freq_switch(on_fs1, on_fs2)
        Freq = str(new_spec1['restfreq'])[0:5]
        mask, mask2, mask3, vll, vrl , peak_vel, peak_vels, num, Order, Order2 = BS.Blocks(new_spec1, h, Auto_Man, Full_YN)
        #pc, NS_off, EW_off = Cpc.calculate_pointing_corr_freq(file_list, file_list2, file_list3, mask, mask2,  peak_vel, half_width, vll, vrl, dirname, Full_YN)
        
        if SM_vel=="Y":
            
            for k in range(0,len(peak_vels), 1):
            
                pc, NS_off, EW_off = Cpch.calculate_pointing_corr_freq(file_list, file_list2, file_list3, mask, mask2, peak_vels[k], half_width, vll, vrl, dirname, Full_YN)
                ONS.append(NS_off)
                OEW.append(EW_off)
                PCT.append(pc) 
            test_point = {'Time' : YFrac, 'Vlsr' : peak_vels, 'PCS': PCT,'OffNS': ONS, 'OffEW': OEW}
            
            #if h==0:
               
            Vlsr_point.update(test_point)
            
            #else:
            
                #for r in range(len(test_point)):
                #    current = test_point[r]
            #    for key, value in test_point.items():
            #        Vlsr_point[key].append(value)
                        
            
            
                
        else:
        
            pc, NS_off, EW_off = Cpc.calculate_pointing_corr_freq(file_list, file_list2, file_list3, mask, mask2, peak_vel, half_width, vll, vrl, dirname, Full_YN)
            
                
        print("# The Pointing correction calculations have been completed!!                            #")
        print("# ===================================================================================== #")
        print("# The Pointing correction factor is: %2.3f " % (pc) )
        print("# ===================================================================================== #")
        print("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
        print("# ===================================================================================== #")
        logging.info("# The Pointing correction calculations have been completed!!                            #")
        logging.info("# ===================================================================================== #")
        logging.info("# The Pointing correction factor is: %2.3f " % (pc) )
        logging.info("# ===================================================================================== #")
        logging.info("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
        logging.info("# ===================================================================================== #")

        spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip = OPF.reduce_point(file_list, file_list2, file_list3, mask, mask2, vll, vrl, Freq, spectra)
        spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip = OPF.full_point_obs(file_list, file_list2, file_list3, num_full_pairs, full_int_on, mask, mask2, vll, vrl, Freq, spectra)

    if num_full_pairs==0 and num_pointing_obs==6 and file_list2[5]=='ON':
        print("# ===================================================================================== #")
        print("# Starting to process Frequency-Switching observations without ON-source observations.  #")
        print("# ===================================================================================== #")
        logging.info("# ===================================================================================== #")
        logging.info("# Starting to process Frequency-Switching observations without ON-source observations.  #")
        logging.info("# ===================================================================================== #")

        on_fs1 = lf.load_file(file_list3[4])
        on_fs2 = lf.load_file(file_list3[5])
        plt.plot(on_fs1['mjd_date']-55000, on_fs1['Cal1_lcp']/1000000)
        plt.plot(on_fs1['mjd_date']-55000, on_fs1['Cal2_rcp']/1000000)
        plt.xlabel('MJD - 55000')
        plt.ylabel('System counts (10$^{6}$)')
        plt.title("Calibration signal for %s " % on_fs1['date'])
        plt.draw()
        plt.pause(0.001)
        plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_fs1['date'][0:10], bbox_inches='tight')
        #plt.show()
        #time.sleep(2)
        if Full_YN == "Yes":
            input("Press Enter to continue")
        
        
        
        #plt.pause(0.001)
        #plt.show()
        #time.sleep(5)
        #plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_fs1['date'][0:10], bbox_inches='tight')
        #plt.show()
        plt.close()

        T_amb = on_fs1['Tamb']
        new_spec1, new_spec2 = Bl.freq_switch(on_fs1, on_fs2)
        Freq = str(new_spec1['restfreq'])[0:5]
        mask, mask2, mask3, vll, vrl, peak_vel, peak_vels, num, Order, Order2 = BS.Blocks(new_spec1, h, Auto_Man, Full_YN)
        #pc, NS_off, EW_off = Cpc.calculate_pointing_corr_freq(file_list, file_list2, file_list3, mask, mask2,  peak_vel, half_width, vll, vrl, dirname, Full_YN)
        
        if SM_vel=="Y":
            
            for k in range(0,len(peak_vels), 1):
            
                pc, NS_off, EW_off = Cpch.calculate_pointing_corr_freq(file_list, file_list2, file_list3, mask, mask2, peak_vels[k], half_width, vll, vrl, dirname, Full_YN)
                ONS.append(NS_off)
                OEW.append(EW_off)
                PCT.append(pc) 
            test_point = {'Time' : YFrac, 'Vlsr' : peak_vels, 'PCS': PCT,'OffNS': ONS, 'OffEW': OEW}
            #if h==0:
            
            Vlsr_point.update(test_point)
            
            #else:
                #for r in range(len(test_point)):
                #    current = test_point[r]
            #    for key, value in test_point.items():
            #        Vlsr_point[key].append(value)
                
                
                                   
                
        else:
        
            pc, NS_off, EW_off = Cpc.calculate_pointing_corr_freq(file_list, file_list2, file_list3, mask, mask2, peak_vel, half_width, vll, vrl, dirname, Full_YN)
            
                
        print("# The Pointing correction calculations have been completed!!                            #")
        print("# ===================================================================================== #")
        print("# The Pointing correction factor is: %2.3f " % (pc) )
        print("# ===================================================================================== #")
        print("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
        print("# ===================================================================================== #")
        logging.info("# The Pointing correction calculations have been completed!!                            #")
        logging.info("# ===================================================================================== #")
        logging.info("# The Pointing correction factor is: %2.3f " % (pc) )
        logging.info("# ===================================================================================== #")
        logging.info("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
        logging.info("# ===================================================================================== #")

        spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip = OPF.reduce_point(file_list, file_list2, file_list3, mask, mask2, vll, vrl, Freq, spectra)


    if num_full_pairs!=0 and num_pointing_obs==0 and file_list2[1]=='OFF':
        print("# ===================================================================================== #")
        print("# Starting to process Position-Switching observations without pointing observations.    #")
        print("# ===================================================================================== #")
        logging.info("# ===================================================================================== #")
        logging.info("# Starting to process Position-Switching observations without pointing observations.    #")
        logging.info("# ===================================================================================== #")

        on_ps1 = lf.load_file(file_list3[full_int_on[0]])
        on_ps2 = lf.load_file(file_list3[full_int_on[1]])
        plt.plot(on_ps1['mjd_date']-55000, on_ps1['Cal1_lcp']/1000000)
        plt.plot(on_ps1['mjd_date']-55000, on_ps1['Cal2_rcp']/1000000)
        #plt.plot(sp_ave['Vlsr'], sp_ave['ave_pol'])
        plt.xlabel('MJD - 55000')
        plt.ylabel('System counts (10$^{6}$)')
        plt.title("Calibration signal for %s " % on_ps1['date'])
    
        plt.draw()
        plt.pause(0.001)
        plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_ps1['date'][0:10], bbox_inches='tight')
        #plt.show()
        #time.sleep(2)
        if Full_YN == "Yes":
            input("Press Enter to continue")
        
        
        
        #plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_fs1['date'][0:10], bbox_inches='tight')
        #plt.show()
        plt.close()


        T_amb = on_ps1['Tamb']
        new_spec1  = Bl.pos_switch(on_ps1, on_ps2)
        Freq = str(new_spec1['restfreq'])[0:5]
        mask, mask2, mask3, vll, vrl, peak_vel, peak_vels, num, Order, Order2 = BS.Blocks(new_spec1, h, Auto_Man, Full_YN)
        spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip = OPF.full_point_obs(file_list, file_list2, file_list3, num_full_pairs, full_int_on ,mask, mask2, vll, vrl, Freq, spectra)
        
        pc = 1.0
        NS_off = 0.0
        EW_off = 0.0


    if num_full_pairs!=0 and num_pointing_obs==0 and file_list2[1]=='ON':
        print("# ===================================================================================== #")
        print("# Starting to process Frequency-Switching observations without pointing observations.   #")
        print("# ===================================================================================== #")
        logging.info("# ===================================================================================== #")
        logging.info("# Starting to process Frequency-Switching observations without pointing observations.   #")
        logging.info("# ===================================================================================== #")

        on_fs1 = lf.load_file(file_list3[full_int_on[0]])
        on_fs2 = lf.load_file(file_list3[full_int_on[1]])
        plt.plot(on_fs1['mjd_date']-55000, on_fs1['Cal1_lcp']/1000000)
        plt.plot(on_fs1['mjd_date']-55000, on_fs1['Cal2_rcp']/1000000)
        plt.xlabel('MJD - 55000 ')
        plt.ylabel('System counts (10$^{6}$)')
        plt.title("Calibration signal for %s " % on_fs1['date'])
    
        plt.draw()
        plt.pause(0.001)
        plt.savefig("../plots/Calibration_signal_%s.pdf"  % on_fs1['date'][0:10], bbox_inches='tight')
        #plt.show()
        if Full_YN == "Yes":
            input("Press Enter to continue")
        
        
        
        #time.sleep(2)
                        #plt.show()
        plt.close()

        T_amb = on_fs1['Tamb']
        new_spec1, new_spec2 = Bl.freq_switch(on_fs1, on_fs2)
        Freq = str(new_spec1['restfreq'])[0:5]
        mask, mask2, mask3, vll, vrl, peak_vel, peak_vels, num, Order, Order2 = BS.Blocks(new_spec1, h, Auto_Man, Full_YN)
        spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip = OPF.full_point_obs(file_list, file_list2, file_list3, num_full_pairs, full_int_on ,mask, mask2, vll, vrl, Freq, spectra)
        pc = 1.0
        NS_off = 0.0
        EW_off = 0.0

    #np.save(PC_vels, Vlsr_point)
    
    #else:

    #    print("None of the options")

    # Extracting the first 4 and 5 characters of the object name and frequency
    OBJ = str(new_spec1['object'])[0:4]
    Freq = str(new_spec1['restfreq'])[0:5]
    if OBJ=='G24.':
        OBJ='G024'
    #spectra = list()
    #HDR = str("Header_info.txt")
    #PC_vels = str('PC_Vels_%s_%s.txt' % (OBJ, Freq))
    #PC=open("../%s" % PC_vels, "a+")
    
    
    F_n = str('Spec_%s_%s_I.txt' % (OBJ, Freq))
    F_n_F = str('Spec_%s_%s_I_Flagged.txt' % (OBJ, Freq))
    F_n_avg = str('Spec_%s_%s_avg.txt' % (OBJ, Freq))
    F_n_l = str('Spec_%s_%s_LCP_K.txt' % (OBJ, Freq))
    F_n_r = str('Spec_%s_%s_RCP_K.txt' % (OBJ, Freq))
    F_n_lpss = str('Spec_%s_%s_LCP_Jy.txt' % (OBJ, Freq))
    F_n_rpss = str('Spec_%s_%s_RCP_Jy.txt' % (OBJ, Freq))
    Stat_1 = str('Stats_%s_%s.txt' % (OBJ, Freq))
    Stat_2 = str('Stats_%s_%s_Flagged.txt' % (OBJ, Freq))
    f=open("../%s" % F_n, "a+")
    f2=open("../%s" % F_n_F, "a+")
    f_avg=open("../%s" % F_n_avg, "a+")
    fl=open("../%s" % F_n_l, "a+")
    fr=open("../%s" % F_n_r, "a+")
    flpss=open("../%s" % F_n_lpss, "a+")
    frpss=open("../%s" % F_n_rpss, "a+")
    
    #with open("myfile.txt", 'w') as f:  
    #    for key, value in details.items():  
    #         f.write('%s:%s\n' % (key, value))
    PC_vels = str('PC_Vels_%s_%s.txt' % (OBJ, Freq))
    #PC=open("../%s" % PC_vels, "a+")
    with open("../%s" % PC_vels, '+a') as f1:
         for key, value in Vlsr_point.items():  
             f1.write('%s:%s\n' % (key, value))
        
    
    np.save(PC_vels, Vlsr_point)            
    #PC=open("../%s" % PPC_1, "a+")
    Stat=open("../%s" % Stat_1, "a+")
    Stat2=open("../%s" % Stat_2, "+a")
    Stat.seek(0)
    new2 = Stat.read(1)
    
    f.seek(0)
    new3 = f.read(1)
    if new3:
         
        lines = len(f.readlines())
        h = lines-2
        
    elif not new3:
    
        logging.info("# File is Empty and Header can be written to File.                                  #")
        print("# File is Empty and Header can be written to File.                                         #")
        h = 0
    
        
            
    # If the Stat is empty then write the Header information into the data file.
    if not new2:
        
        logging.info("# File is Empty and Header can be written to File.                                  #")
        print("# File is Empty and Header can be written to File.                                         #")
        Stat.write("%s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s  %s \n" % ("#OBS#", "#UTC                ", "MJD        ", "Y FRaction", "TSYS_LCP", "TSYS_RCP", "T_Amb", "RMS", "PC", "AT_Corr", "PWV(mm)" , "Ele_ang", "Az_ang", "NS_offset", "EW_offset", "PSS_LCP", "PSS_RCP", "max(Avg(K))", "max(LCP)", "max(RCP)", "max(I)"))

    
    print("# ===================================================================================== #")
    print("# For %s the System temperatures are %3.2f (K) LCP and %3.2f (K) RCP"  % (Obs_T, tsys_l, tsys_r))
    logging.info("# ===================================================================================== #")
    logging.info("# For %s the System temperatures are %3.2f (K) LCP and %3.2f (K) RCP"  % (Obs_T, tsys_l, tsys_r))

    #print("# ===================================================================================== #")
    #print("# The Pointing correction factor is: \033[42m %2.3f \033[0m " % (pc) )
    #print("# ===================================================================================== #")
    #print("# and the associated N-S offset is:\033[42m  %2.3f \033[0m deg, and the E-W offset is:\033[42m  %2.3f  \033[0m deg" % (NS_off, EW_off))
    #print("# ===================================================================================== #")
    #print("# The Pointing correction factor is: %2.3f " % (pc) )
    #print("# ===================================================================================== #")
    #print("# and the associated N-S offset is: %2.3f deg, and the E-W offset is: %2.3f deg" % (NS_off, EW_off))
    #print("# ===================================================================================== #")
    LCP_PSS = 0.0
    RCP_PSS = 0.0

    # Calculate the average spectrum
    final_spec  = Pols.ave_spec(spectra)
    print(final_spec['date'])
    #plot_spec.plot_spec(final_spec)
    t = Time(final_spec['date'], format='iso', scale='utc')
    tyd = t.mjd

    # Retrieve the LCP and RCP PSS values.
    LCP_PSS, RCP_PSS = CPP.PSS(Freq, tyd)
    #print("# ===================================================================================== #")
    #print("# The (PSS) values for \033[91m %s \033[0m is \033[42m %2.3f \033[0m for LCP and \033[42m %2.3f \033[0m for RCP " % (Obs_T, LCP_PSS, RCP_PSS))
    #print("# ===================================================================================== #")
    #print("# The Max LCP: \033[42m %2.3f  \033[0m, and Max RCP \033[42m  %2.3f  \033[0m" % (max(final_spec['LCP']),max(final_spec['RCP'])))
    #print("# ===================================================================================== #")
    print("# The (PSS) values for %s is %2.3f for LCP and %2.3f for RCP " % (Obs_T, LCP_PSS, RCP_PSS))
    print("# ====================================================================================== #")
    print("# The Max LCP: %2.3f, and Max RCP %2.3f " % (max(final_spec['LCP']),max(final_spec['RCP'])))
    print("# ====================================================================================== #")
    logging.info("# The (PSS) values for %s is %2.3f for LCP and %2.3f for RCP " % (Obs_T, LCP_PSS, RCP_PSS))
    logging.info("# ====================================================================================== #")
    logging.info("# The Max LCP: %2.3f, and Max RCP %2.3f " % (max(final_spec['LCP']),max(final_spec['RCP'])))
    logging.info("# ====================================================================================== #")

    Ave_spec = Pols.ave_pols(final_spec)
    #print(max(final_spec['LCP']),max(final_spec['RCP']))
    LCP_spec = final_spec['LCP']*pc
    RCP_spec = final_spec['RCP']*pc
        
    final_spec['LCP'] = LCP_spec*LCP_PSS
    final_spec['RCP'] = RCP_spec*RCP_PSS
    k = 0
    Max = 0
    
    # Add polarizations to get Stokes I
    final_spec = Pols.add_pols(final_spec)

    # RMS calculates the RMS noise from the selected baseline blocks and display them in another color in the final plot
    rms, Max = St.rms_stn(final_spec['I'],final_spec['Vlsr'], mask, mask3, vll, vrl, peak_vel, dirname, final_spec['object'], final_spec['date'])
    #print("# ===================================================================================== #")

    #print("# ===================================================================================== #")
    print("# The Maximum flux for the Spectrum is: %4.2f Jy" % (Max) )
    print("# ===================================================================================== #")
    print("# The RMS noise of %s is %2.3f Jy " % (Obs_T, rms))
    print("# ===================================================================================== #")
    logging.info("# The Maximum flux for the Spectrum is: %4.2f Jy" % (Max) )
    logging.info("# ===================================================================================== #")
    logging.info("# The RMS noise of %s is %2.3f Jy " % (Obs_T, rms))
    logging.info("# ===================================================================================== #")

    # Uses UTC and converts to MJD to write into file
    t = Time(final_spec['date'], format='iso', scale='utc')
    tyd = t.mjd
    
    #print("# ===================================================================================== #")
    print("# The weigthed Modified Julian Date (MJD) of this observation is: %5.3f MJD" % (tyd) )
    print("# ===================================================================================== #")
    logging.info("# The weigthed Modified Julian Date (MJD) of this observation is: %5.3f MJD" % (tyd) )
    logging.info("# ===================================================================================== #")
    rms_L = 1.2
    #pc = 1.2
    #N_off = np.abs(0.025)
    #E_off= np.abs(0.025)
    
    if Freq == "66685" or Freq == "16654" or Freq =="16673" or Freq == "46605" or Freq == "48293" or Freq == "6708.":
        
        rms_L = 1.2
        if rms > rms_L or pc > 1.25:
        
            k = h
            
        elif (0.8 < rms < 1.2):
        
            k = h
    
        elif rms < rms_L:
        
            k = 0.0
    
    elif Freq == "12178":
        
        rms_L = 1.2
        if rms > rms_L or pc > 1.25:
        
            k = h
        elif (0.8 < rms < 1.2):
        
            k = h
    
        elif rms < rms_L:
        
            k = 0.0
    
            
    elif Freq == "22235":
    
        rms_L = 2.0
        
        if rms > rms_L:
        
            k = h
        
        elif (1.5 < rms < 2.0):
        
            k = h
        
        elif rms < rms_L:
        
            k = 0
    

    Vl_new = np.hstack([0, 0,0, 0,final_spec['Vlsr']])
    Fd_new = np.hstack([h, k, tyd,YFrac,final_spec['I']])
    Fd_new_avg = np.hstack([h, k, tyd, YFrac, Ave_spec['ave_pol']])
    Fd_l_K = np.hstack([h, k, tyd,YFrac,LCP_spec])
    Fd_r_K = np.hstack([h, k, tyd,YFrac,RCP_spec])
    Fd_lnew = np.hstack([h, k, tyd,YFrac,final_spec['LCP']])
    Fd_rnew = np.hstack([h, k, tyd,YFrac,final_spec['RCP']])
    
    #Fd_lnew2 = np.hstack([h, k, tyd,YFrac,LCP_spec])
    #Fd_rnew2 = np.hstack([h, k, tyd,YFrac,RCP_spec])
    
    m_avg = np.max(Ave_spec['ave_pol'])
    m_fs_L  = np.max(final_spec['LCP'])
    m_fs_R  = np.max(final_spec['RCP'])
    m_fs_I  = np.max(final_spec['I'])
    
    #print(m_avg, m_fs_L, m_fs_R, m_fs_I)
        
    Stat.write("%i  %i  %s  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f %5.5f  %5.5f  %5.5f \n" % (h, k, t, tyd, YFrac, tsys_l, tsys_r, T_amb, rms, pc, ATcor, precip, Elev_ang, Az_deg, NS_off, EW_off, LCP_PSS, RCP_PSS, m_avg, m_fs_L, m_fs_R, m_fs_I))

    if k != 0:
  
        Stat2.write("%i  %i  %s  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f %5.5f  %5.5f  %5.5f \n" % (h, k, t, tyd, YFrac, tsys_l, tsys_r, T_amb, rms, pc, ATcor, precip, Elev_ang, Az_deg, NS_off, EW_off, LCP_PSS, RCP_PSS, m_avg, m_fs_L, m_fs_R, m_fs_I))
 
        #Stat2.write("%s  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f  %5.5f %5.5f  %5.5f  %5.5f \n" % (t, tyd, YFrac, tsys_l, tsys_r, T_amb, rms, pc, ATcor, Elev_ang, Az_deg, NS_off, EW_off, LCP_PSS, RCP_PSS, m_avg, m_fs_L, m_fs_R, m_fs_I))


    f.seek(0)
    new = f.read(1)

    if not new:
        print('File is Empty')
        for item in Vl_new:
            f.write("%5.5f  " % item)
            f2.write("%5.5f  " % item)
            f_avg.write("%5.5f  " % item)
            fl.write("%5.5f  " % item)
            fr.write("%5.5f  " % item)
            flpss.write("%5.5f  " % item)
            frpss.write("%5.5f  " % item)
        f.write("\n")
        f2.write("\n")
        f_avg.write("\n");
        fl.write("\n")
        fr.write("\n")
        flpss.write("\n")
        frpss.write("\n")
        
         

        for item in Fd_new:
                    
                f.write("%5.5f  " % item)
                f2.write("5.5f  " % item)    
        #    f_avg.write("%5.5f  " % item)
        f.write("\n")
        f2.write("\n")
        
        for item2 in Fd_new_avg:
            f_avg.write("%5.5f  " % item2)
        f_avg.write("\n")
        
        for item in Fd_lnew:
            fl.write("%5.5f  " % item)

        fl.write("\n")
        for item in Fd_rnew:
            fr.write("%5.5f  " % item)

        fr.write("\n")
        
        for item in Fd_l_K:
            flpss.write("%5.5f  " % item)

        flpss.write("\n")
        for item in Fd_r_K:
            frpss.write("%5.5f  " % item)

        frpss.write("\n")
               
        h+=1

    else:
        print('File is not empty')
        for item in Fd_new:
                   
                f.write("%5.5f  " % item)
                f2.write("%5.5f  " % item)
                
        f.write("\n")
        f2.write("\n")
        
        for item2 in Fd_new_avg:
            f_avg.write("%5.5f  " % item2)
        f_avg.write("\n")
        
        for item in Fd_lnew:
            fl.write("%5.5f  " % item)

        fl.write("\n")
        for item in Fd_rnew:
            fr.write("%5.5f  " % item)

        fr.write("\n")
        
        for item in Fd_l_K:
            flpss.write("%5.5f  " % item)

        flpss.write("\n")
        for item in Fd_r_K:
            frpss.write("%5.5f  " % item)

        frpss.write("\n")
        
        



    DN = work_dir+'Done/'
    print(os.system(cwd))
    print(Vlsr_point)
    #Final_plot(F_n, F2, OBJ, Freq)

    #DD.remove(dirname)
    #print(work_dir+'Done/')

    shutil.move(work_dir+dirname, DN)

    f.close()
    fl.close()
    fr.close()

    Stat.close()
    h+=1
    #Auto_Man = ""
    #time.sleep(2)
    # Here you can take out the input and the code will automatically run through all the observations and reduce the data.
    if Auto_Man =="":

       Auto_Man, Full_YN = OPT.Option()


    #Auto_Man = input("Do you want to automate the reduction or manually inspect the reduction process? (Auto/Man)")
    elif Auto_Man == "Man" or Auto_Man =="man":

        Ans=input('Is there another observation available? (Y/N)')
        if Ans =="Y" or Ans =="y" and h>=1:
            print('Continue processing manually')


        #elif Ans =="N" or Ans =="n" and h==0:

        #    Auto_Man = "Auto"
        elif Ans =="N" or Ans =="n" and h!=0:

            break

        #print("All of the observations will now be processed automatically")

    elif Auto_Man =="Auto" or Auto_Man =="auto":

        print("All of the observations will now be processed automatically")

    
    #h+=1
    plt.close()
    plt.clf()
    #sys,stdout.close()
os.system("cd ../")

