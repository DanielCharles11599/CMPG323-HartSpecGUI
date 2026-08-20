

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
import ipywidgets as widgets
import threading
import asyncio
#import pyspeckit


def Option():

   #Auto_Man = "Auto"
   
   #if Auto_Man
   
   ANS = input("Do you want to process the data Automatically of Manually?(Auto/Man)")
       
   ANS2= input("After selecting MANUAL, do you want to make all the selections or only whether to continue to the next OBSERVATION?(Yes/No)")    
   #if ANS = "Auto" or "auto":
      
   return ANS, ANS2   




