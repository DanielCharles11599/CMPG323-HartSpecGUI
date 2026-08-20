#------------------------------------------------------------------------------#
# Imports

from astropy.io import fits as pyfits
from astropy.io import ascii
from astropy.time import Time
from os import path
from astropy.time import Time
from scipy.optimize import curve_fit
from platform import python_version

import numpy as np
import matplotlib.pyplot as plt
import os
import pickle
import shutil
import time

cwd = os.getcwd()
#print(cwd)

def File_err(file_list, Src, Fr):
    """
    This function tests if any of the files in the observation misses any of the keywords in the header, i.e. TSYS1 or TSYS2.
    """
    print("This means there are files which do not have sufficient information to process ACCURATELY")
    time.sleep(2)
    po = 0
    On = 0
    cwd = os.getcwd()
    print(cwd)
    f=open("../Source_observation_logfile.txt", "a")
    j=0
    
    for i in range(1, len(file_list)):
         
        hdul1 = pyfits.open(file_list[j])
        hdul2 = pyfits.open(file_list[i])
        hdu1  = list(hdul1[3].header.keys())
        hdu2  = list(hdul2[3].header.keys())
        posi    = str(hdul2[2].header['POSITION'])
        point   = str(hdul2[0].header['SPPOINT'])
        if hdul1[3].header['TCAL1']:
        
           hdul1[3].header['TSYS1'] = hdul1[3].header['TCAL1']
           hdul1[3].header['TSIG1'] = hdul1[3].header['TSYSERR1']
           hdul1[3].header['TSYS2'] = hdul1[3].header['TCAL2']
           hdul1[3].header['TSIG2'] = hdul1[3].header['TSYSERR2']
         
        BadArr = list(set(hdu1) - set(hdu2))
        BadArr2= list(set(hdu2) - set(hdu1))
        #print(hdu1[3])
        #print(str(hdul1[3].header['TCAL1']))
        #print(hdu2)
        
        
        if (len(BadArr) == 0 and len(BadArr2) != 0) and point =="1":
            j=1
            po = po + 1
            time.sleep(2)
                    
        elif (len(BadArr) != 0 or len(BadArr2) != 0) and point =="1":
                 
        #if (len(BadArr) != 0 or len(BadArr2) != 0) and point =="1":
        
            po = po + 1
            time.sleep(2)
        #elif     
            
        elif (len(BadArr) != 0 or len(BadArr2) != 0) and point =="0":
        
            On = On + 1
            time.sleep(2)
    #print(os.getcwd)
    j=0
    if po == 0 and On == 0:
    
        List = file_list
        for i in range(len(List)):
            f.write("%s is part of a complete set of observations \n" % List[i])
                
    elif po != 0 and On == 0:
        
        for e in range(0, 6,1):
            f.write("File %s is corrupted and cannot be used for pointing correction checks \n" % file_list[e])
            shutil.move(cwd+'/'+file_list[e],cwd+'/../'+"Flagged/") 
        List = file_list[-5:]
        print(List)
        
    elif po == 0 and On != 0:
        for e in range(6,10,1):
            f.write("One or more of these files including %s are corrupt and none of these can be used for on-source integration \n" % file_list[e])
            
            shutil.move(cwd+'/'+file_list[e], cwd+'/../'+"Flagged/")
        List = file_list[0:6]
        print(List)
        
    elif po != 0 and On != 0:
    
        for e in range(0,9,1):
            f.write("There are corrupt files in both the pointing observations and On-source, Thus %s can not be used \n" % file_list[e])
            shutil.move(cwd+'/'+file_list[e], cwd+'/../'+"Flagged/")
            
        print("Continue")
        
        
        
        
    f.close()        
    print(po, On)
             
    return List         

       
                