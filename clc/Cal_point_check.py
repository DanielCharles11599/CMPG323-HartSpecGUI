#------------------------------------------------------------------------------------------------#
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

import load_file as lf
import Baseline as Bl
import Flat_base as Fb
import fit_max as fm
import Point_cor as Pc
import Pols as Pols
import Stats_manager as St


def calculate_pointing_corr_freq(file_list, file_list2, file_list3, mask, mask2, peak_vel, half_width, vll, vrl, dirname, Full_YN):
    """
    This function is used to calculate how good the telescope is pointing to the source it observes. Firstly, it loads the 6 data files 
    N, S, E, W, ON, ON. Does frequency-switching on the spectra for (N-S), (E-w) and the two ON's. After that it is fed into the 
    flatten-baseline function to flatten out the baseline. After the baseline is flattened, the individual peaks are tested to see if 
    they are strong enough to do pointing correction, if any of the pointing's peak is below 3 sigma of the noise, then no pointing 
    correction is applied and the pointing correction factor is set to 1. If the pointing correction is done, the pointing correction 
    factor is obtained and off-sets in the N-S and E-W directions are derived from a Gaussian fit. 
    
    """
    
    hpn = lf.load_file(file_list3[np.where(file_list2=='HPN')][0])
    hps = lf.load_file(file_list3[np.where(file_list2=='HPS')][0])
    hpe = lf.load_file(file_list3[np.where(file_list2=='HPE')][0])
    hpw = lf.load_file(file_list3[np.where(file_list2=='HPW')][0])
    on_point = np.where(np.logical_and(file_list2=='ON', file_list['pointing']==1))[0]
    
    on1 = lf.load_file(file_list3[on_point[0]])
    on2 = lf.load_file(file_list3[on_point[1]])
    hpn_corr, hps_corr = Bl.freq_switch(hpn, hps)
    hpe_corr, hpw_corr = Bl.freq_switch(hpe, hpw)
    on1_corr, on2_corr = Bl.freq_switch(on1,on2)
    
    hpn_corr['LCP'], hpn_corr['RCP'] = Fb.flatten_baseline2(hpn_corr['Vlsr'], hpn_corr['LCP'], hpn_corr['RCP'], vll, vrl, mask, mask2)
    #hpn_corr['RCP'] = flatten_baseline2(hpn_corr['Vlsr'], hpn_corr['RCP'], mask2, Order2)

    hps_corr['LCP'], hps_corr['RCP'] = Fb.flatten_baseline2(hps_corr['Vlsr'], hps_corr['LCP'], hps_corr['RCP'], vll, vrl, mask, mask2)
    #hps_corr['RCP'] = flatten_baseline2(hps_corr['Vlsr'], hps_corr['RCP'], mask2, Order2)

    hpe_corr['LCP'], hpe_corr['RCP'] = Fb.flatten_baseline2(hpe_corr['Vlsr'], hpe_corr['LCP'], hpe_corr['RCP'], vll, vrl, mask , mask2)
    #hpe_corr['RCP'] = flatten_baseline2(hpe_corr['Vlsr'], hpe_corr['RCP'], mask2, Order2)

    hpw_corr['LCP'], hpw_corr['RCP'] = Fb.flatten_baseline2(hpw_corr['Vlsr'], hpw_corr['LCP'], hpw_corr['RCP'], vll, vrl, mask, mask2)
    #hpw_corr['RCP'] = flatten_baseline2(hpw_corr['Vlsr'], hpw_corr['RCP'], mask2, Order2)

    on1_corr['LCP'], on1_corr['RCP'] = Fb.flatten_baseline2(on1_corr['Vlsr'], on1_corr['LCP'], on1_corr['RCP'], vll, vrl, mask, mask2)
    #on1_corr['RCP'] = flatten_baseline2(on1_corr['Vlsr'], on1_corr['RCP'], mask2, Order2)

    on2_corr['LCP'], on2_corr['RCP'] = Fb.flatten_baseline2(on2_corr['Vlsr'], on2_corr['LCP'], on2_corr['RCP'], vll, vrl, mask, mask2)
    #o
        
    #average polarisations to improve signal to noise ratio
    hpn_corr = Pols.ave_pols(hpn_corr)
    hps_corr = Pols.ave_pols(hps_corr)
    hpe_corr = Pols.ave_pols(hpe_corr)
    hpw_corr = Pols.ave_pols(hpw_corr)
    centre_point = Pols.ave_pols(on1_corr)
    pc_f = 1
    pc = 1
    G_ahead=""
    NS_off = 0
    EW_off = 0
    # Determine if pointing correction calculations can be done.
    G_ahead = St.Sig_point(hpn_corr['ave_pol'], hps_corr['ave_pol'], hpe_corr['ave_pol'], hpw_corr['ave_pol'], centre_point['ave_pol'], hpn_corr['Vlsr'], mask, peak_vel)
    
    if G_ahead=="No":
    
         G_ahead="Yes"
         
         
    # Smooth the rms noise
    hpn_corr['ave_pol'] = savgol_filter(hpn_corr['ave_pol'], 7, 3)
    hps_corr['ave_pol'] = savgol_filter(hps_corr['ave_pol'], 7, 3)
    hpe_corr['ave_pol'] = savgol_filter(hpe_corr['ave_pol'], 7, 3)
    hpw_corr['ave_pol'] = savgol_filter(hpw_corr['ave_pol'], 7, 3)
    centre_point['ave_pol'] = savgol_filter(centre_point['ave_pol'], 7, 3)
    #Make a plot
    
    plt.figure(figsize=[7,7])
    #plt.ion()
    #if Full_YN=="Yes" or Full_YN=="yes":
    
    plt.suptitle('Pointing observations for '+dirname)
    plt.subplot(332)
    plt.title('North')
    plt.plot(hpn_corr['Vlsr'], hpn_corr['ave_pol'], label='North')
    plt.subplot(334)
    plt.title('East')
    plt.plot(hpe_corr['Vlsr'], hpe_corr['ave_pol'], label='East')
    plt.subplot(335)
    plt.title('Centre')
    plt.plot(centre_point['Vlsr'], centre_point['ave_pol'], label='Centre')
    plt.subplot(336)
    plt.title('West')
    plt.plot(hpw_corr['Vlsr'], hpw_corr['ave_pol'], label='West')
    plt.subplot(338)
    plt.title('South')
    plt.plot(hps_corr['Vlsr'], hps_corr['ave_pol'], label='South')
    #plt.legend()
    plt.tight_layout()
    plt.savefig("../plots/Pointing_for_%s_%s.pdf" % (dirname[0:8], str(peak_vel)), bbox_inches='tight')
    
    if Full_YN=="Yes" or Full_YN=="yes":
    
        plt.close()
        
    elif Full_YN=="No" or Full_YN=="":
    
        plt.draw()
        plt.pause(0.001)
        time.sleep(5)
        plt.close()
    #plt.draw()
    #plt.pause(0.001)
    #time.sleep(2)
    #plt.close()
       
    ord = 3 #polynomial order for peak fit
    fig = plt.figure(figsize=[10,2])
    plt.ion()
    plt.suptitle('Peak fits for pointing observations on  '+dirname)
    plt.subplot(151)
    plt.title('North')
    CH, north, n1, n2 = fm.fit_max(hpn_corr, peak_vel, half_width, ord)
    plt.plot(hpn_corr['Vlsr'][CH], hpn_corr['ave_pol'][CH], 'ko')
    plt.plot(n1, n2, 'r')
    plt.subplot(152)
    plt.title('South')
    CH, south, s1, s2 = fm.fit_max(hps_corr, peak_vel, half_width, ord)
    plt.plot(hps_corr['Vlsr'][CH], hps_corr['ave_pol'][CH], 'ko')
    plt.plot(s1, s2, 'r')
    plt.subplot(153)
    plt.title('East')
    CH, east, e1, e2 = fm.fit_max(hpe_corr, peak_vel, half_width, ord)
    plt.plot(hpe_corr['Vlsr'][CH], hpe_corr['ave_pol'][CH], 'ko')
    plt.plot(e1, e2, 'r')
    plt.subplot(154)
    plt.title('West')
    CH, west, w1, w2 = fm.fit_max(hpw_corr, peak_vel, half_width, ord)
    plt.plot(hpw_corr['Vlsr'][CH], hpw_corr['ave_pol'][CH], 'ko')
    plt.plot(w1, w2, 'r')
    plt.subplot(155)
    plt.title('Centre')
    CH, cen, c1, c2 = fm.fit_max(centre_point, peak_vel, half_width, ord)
    plt.plot(centre_point['Vlsr'][CH], centre_point['ave_pol'][CH], 'ko')
    plt.plot(c1, c2, 'r')
    
    fig.tight_layout()
    plt.savefig("../plots/Gauss_point_for_%s_%s.pdf" % (dirname[0:8], str(peak_vel)), bbox_inches='tight')
    
    if Full_YN=="Yes" or Full_YN=="yes":
    
        plt.close()
    
    elif Full_YN=="No" or Full_YN=="":
   
        plt.draw()
        plt.pause(0.001)
        time.sleep(5)
    
    plt.close()     
    #plt.draw()
    #plt.pause(0.001      #time.sleep(2)
    #plt.close()
    #plt.clf()
    global hpbw #I really shouldn't do this - its because of the way I am doing the Gaussian fit.
    hpbw = centre_point['HPBW']
    
    if G_ahead=="Yes":
        pc, NS_off, EW_off= Pc.pointcor(north, south, east, west, cen, hpbw, dirname)
    #elif G_ahead=="Half":
    #    pc = np.exp(pc_f)
    #    NS_off = 0
    #    EW_off = 0
    elif G_ahead=="No":
        pc = 1.0
        NS_off = 0
        EW_off = 0
        
    #print ('Pointing correction factor', pc)
    return pc, NS_off, EW_off
    
#file_list, file_list2, file_list3, vll, vrl, mask, mask2, peak_vel

def calculate_pointing_corr_pos(file_list, file_list2, file_list3, mask, mask2, peak_vel, half_width, vll, vrl, dirname, Full_YN):
    """
    This function is used to calculate how good the telescope is pointing to the source it observes. Firstly, it loads the 6 data files 
    N, S, E, W, ON, OFF. Does position-switching on the spectra for (N-OFF), (S-OFF), (E-OFF), (W-OFF) and (ON-OFF). After that it is fed into the 
    flatten-baseline function to flatten out the baseline. After the baseline is flattened, the individual peaks are tested to see if 
    they are strong enough to do pointing correction, if any of the pointing's peak is below 3 sigma of the noise, then no pointing 
    correction is applied and the pointing correction factor is set to 1. If the pointing correction is done, the pointing correction 
    factor is obtained and off-sets in the N-S and E-W directions are derived from a Gaussian fit. 
    
    """
    hpn = lf.load_file(file_list3[np.where(file_list2=='HPN')][0])
    hps = lf.load_file(file_list3[np.where(file_list2=='HPS')][0])
    hpe = lf.load_file(file_list3[np.where(file_list2=='HPE')][0])
    hpw = lf.load_file(file_list3[np.where(file_list2=='HPW')][0])

    on1 = lf.load_file(file_list3[4])
    off1 = lf.load_file(file_list3[5])
    hpn_corr = Bl.pos_switch(hpn,off1)
    hps_corr = Bl.pos_switch(hps,off1)
    hpe_corr = Bl.pos_switch(hpe,off1)
    hpw_corr = Bl.pos_switch(hpw,off1)
    on1_corr = Bl.pos_switch(on1,off1)
    
    hpn_corr['LCP'], hpn_corr['RCP'] = Fb.flatten_baseline2(hpn_corr['Vlsr'], hpn_corr['LCP'], hpn_corr['RCP'], vll, vrl, mask, mask2)
    #hpn_corr['RCP'] = flatten_baseline2(hpn_corr['Vlsr'], hpn_corr['RCP'], mask2, Order2)
    hps_corr['LCP'], hps_corr['RCP'] = Fb.flatten_baseline2(hps_corr['Vlsr'], hps_corr['LCP'], hps_corr['RCP'], vll, vrl, mask, mask2)
    #hps_corr['RCP'] = flatten_baseline2(hps_corr['Vlsr'], hps_corr['RCP'], mask2, Order2)

    hpe_corr['LCP'], hpe_corr['RCP'] = Fb.flatten_baseline2(hpe_corr['Vlsr'], hpe_corr['LCP'], hpe_corr['RCP'], vll, vrl, mask, mask2)
    #hpe_corr['RCP'] = flatten_baseline2(hpe_corr['Vlsr'], hpe_corr['RCP'], mask2, Order2)

    hpw_corr['LCP'], hpw_corr['RCP'] = Fb.flatten_baseline2(hpw_corr['Vlsr'], hpw_corr['LCP'], hpw_corr['RCP'], vll, vrl, mask, mask2)
    #hpw_corr['RCP'] = flatten_baseline2(hpw_corr['Vlsr'], hpw_corr['RCP'], mask2, Order2)

    on1_corr['LCP'], on1_corr['RCP'] = Fb.flatten_baseline2(on1_corr['Vlsr'], on1_corr['LCP'], on1_corr['RCP'], vll, vrl, mask, mask2)
    #
    
    #average polarisations to improve signal to noise ratio
    hpn_corr = Pols.ave_pols(hpn_corr)
    hps_corr = Pols.ave_pols(hps_corr)
    hpe_corr = Pols.ave_pols(hpe_corr)
    hpw_corr = Pols.ave_pols(hpw_corr)
    centre_point = Pols.ave_pols(on1_corr)
    pc_f = 1
    pc = 1
    G_ahead=""
    NS_off = 0
    EW_off = 0
    # Determine if pointing correction can be done. 
    G_ahead = St.Sig_point(hpn_corr['ave_pol'], hps_corr['ave_pol'], hpe_corr['ave_pol'], hpw_corr['ave_pol'], centre_point['ave_pol'], hpn_corr['Vlsr'], mask,  peak_vel)
    
    if G_ahead=="No":
    
        G_ahead="Yes"
    
    # Smooth the rms noise.
    hpn_corr['ave_pol'] = savgol_filter(hpn_corr['ave_pol'], 7, 3)
    hps_corr['ave_pol'] = savgol_filter(hps_corr['ave_pol'], 7, 3)
    hpe_corr['ave_pol'] = savgol_filter(hpe_corr['ave_pol'], 7, 3)
    hpw_corr['ave_pol'] = savgol_filter(hpw_corr['ave_pol'], 7, 3)
    centre_point['ave_pol'] = savgol_filter(centre_point['ave_pol'], 7, 3)

    #Make a plot
    
    plt.figure(figsize=[10,10])
    #plt.ion()
    plt.suptitle('Pointing observations for '+dirname)
    plt.subplot(332)
    plt.title('North')
    plt.plot(hpn_corr['Vlsr'], hpn_corr['ave_pol'], label='North')# 'ave_pol'
    plt.subplot(334)
    plt.title('East')
    plt.plot(hpe_corr['Vlsr'], hpe_corr['ave_pol'], label='East')
    plt.subplot(335)
    plt.title('Centre')
    plt.plot(centre_point['Vlsr'], centre_point['ave_pol'], label='Centre')
    plt.subplot(336)
    plt.title('West')
    plt.plot(hpw_corr['Vlsr'], hpw_corr['ave_pol'], label='west')
    plt.subplot(338)
    plt.title('South')
    plt.plot(hps_corr['Vlsr'], hps_corr['ave_pol'], label='South')
    plt.tight_layout()
    plt.savefig("../plots/Pointing_for_%s_%s.pdf" % (dirname[0:8], str(peak_vel)), bbox_inches='tight')
    
    if Full_YN=="Yes" or Full_YN=="yes":
    
        plt.close()
        
    elif Full_YN=="No" or Full_YN=="":
    
        plt.draw()
        plt.pause(0.001)
        time.sleep(5)
        plt.close()
    
    
    #plt.draw()
    #plt.pause(0.001)
    #time.sleep(2)
    #plt.close()
    ord = 3 #polynomial order for peak fit
    fig = plt.figure(figsize=[10,2])
    #plt.ion()
    #plt.ion()
    plt.suptitle('Peak fits for pointing observations on  '+dirname)
    plt.subplot(151)
    plt.title('North')
    CH, north, n1, n2 = fm.fit_max(hpn_corr, peak_vel, half_width, ord)
    plt.plot(hpn_corr['Vlsr'][CH], hpn_corr['ave_pol'][CH], 'ko')
    plt.plot(n1, n2, 'r')
    plt.subplot(152)
    plt.title('South')
    CH, south, s1, s2 = fm.fit_max(hps_corr, peak_vel, half_width, ord)
    plt.plot(hps_corr['Vlsr'][CH], hps_corr['ave_pol'][CH], 'ko')
    plt.plot(s1, s2, 'r')
    plt.subplot(153)
    plt.title('East')
    CH, east, e1, e2 = fm.fit_max(hpe_corr, peak_vel, half_width, ord)
    plt.plot(hpe_corr['Vlsr'][CH], hpe_corr['ave_pol'][CH], 'ko')
    plt.plot(e1, e2, 'r')
    plt.subplot(154)
    plt.title('West')
    CH, west, w1, w2 = fm.fit_max(hpw_corr, peak_vel, half_width, ord)
    plt.plot(hpw_corr['Vlsr'][CH], hpw_corr['ave_pol'][CH], 'ko')
    plt.plot(w1, w2, 'r')
    plt.subplot(155)
    plt.title('Centre')
    CH, cen, c1, c2 = fm.fit_max(centre_point, peak_vel, half_width, ord)
    plt.plot(centre_point['Vlsr'][CH], centre_point['ave_pol'][CH], 'ko')
    plt.plot(c1, c2, 'r')
    fig.tight_layout()
    plt.savefig("../plots/Gauss_point_for_%s_%s.pdf" % (dirname[0:8], str(peak_vel)), bbox_inches='tight')
    
    if Full_YN=="Yes" or Full_YN=="yes":
    
        plt.close()
        
    elif Full_YN=="No" or Full_YN=="":
    
        plt.draw()
        plt.pause(0.001)
        time.sleep(5)
        #plt.close()
    
    #plt.draw()
    #plt.pause(0.001)
    #time.sleep(2)
    #plt.show()
    plt.close()
    #plt.clf()
    
    global hpbw #I really shouldn't do this - its because of the way I am doing the Gaussian fit.
    hpbw = centre_point['HPBW']
    
    if G_ahead=="Yes":
        pc, NS_off, EW_off= Pc.pointcor(north, south, east, west, cen, hpbw, dirname)
        
    #elif G_ahead=="Half":
    #    pc = np.exp(pc_f)
    #    NS_off = 0
    #    EW_off = 0
        
    elif G_ahead=="No":
        pc = 1.0
        NS_off = 0
        EW_off = 0
    #print ('Pointing correction factor', pc)
    return pc, NS_off, EW_off
    
