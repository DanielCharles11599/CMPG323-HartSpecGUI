#! /home/fvdheever/Work/HartRAO_software/HartSpecPack/venv/
from astropy.io import fits as pyfits
import numpy as np
import matplotlib.pyplot as plt
import array as array
import os
import sys
import re
import shutil
from os import path
from astropy.time import Time
from scipy.optimize import curve_fit
from bullet import Bullet
import subprocess
#import HartSpec
beg = os.getcwd()

def interaction():
#cwd = os.getcwd()
    os.chdir('data')
    cwd = os.getcwd()
    #print(cwd)
    Direc = next(os.walk('.'))[1]



    cli = Bullet(
        prompt = "\nPlease choose a Source: ",
        choices = Direc, 
        indent = 0,
        align = 5, 
        margin = 2,
        shift = 0,
        bullet = "",
        pad_right = 5,
        return_index = True
    )

    result = cli.launch()
    #print("You chose:", result)

    os.chdir('.'+'/'+result[0]) 
 
    Freq = next(os.walk('.'))[1]

    cli = Bullet(
        prompt = "\nPlease choose a Frequency: ",
        choices = Freq, 
        indent = 0,
        align = 5, 
        margin = 2,
        shift = 0,
        bullet = "",
        pad_right = 5,
        return_index = True
    )

    result2 = cli.launch()
    os.chdir(beg)
    #print("You chose:", result2)
    return result[0], result2[0]
#os.chdir('./../../')
#cwd = os.getcwd()
#print(cwd)
#subprocess.run("python3 HartSpec.py %s %s" % (result[0], result2[0]))
#os.sys("python3 HartSpec.py %s %s" % (result[0], result2[0]))


