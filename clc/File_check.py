#!/usr/bin/env python3
"""File_check.py -- sorts a source/frequency folder of FITS files into observation blocks.

PHASE 0 (GUI-integration) REVISION -- authorised by the system owners (UAT feedback, "Raised issues").
The sorting state machine below (every if/elif branch, including the duplicated elif guards, and every
counter/pointobs update) is UNCHANGED, line for line. Only I/O plumbing changed:

  A. Was a bare top-level script; now `run_file_check(observation, frequency, base_dir)`.
     Importing it no longer executes anything, so a second call in the same Streamlit process works.
  B. `IAT.interaction()` (terminal input()) replaced by the `observation` / `frequency` arguments.
     `import Interact` and the unused `import File_Manage` / `matplotlib` removed.
  C. `os.chdir(work_dir)` removed. It changed the working directory of the whole shared server process, so
     every relative path in the app (e.g. FITS_ARCHIVE_PATH=./data/fits) broke after the first run. All
     paths are now explicit, rooted at `base_dir/<observation>/<frequency>/` (helper `_wd`).
  D. `os.system('ls *.fits > fits_list.txt')` replaced by an equivalent sorted listing (no shell, works on Windows).
  E. Imports of `load_file` made robust to being loaded as `clc.File_check` or as a bare module.
  F. Re-run safety: previous .txt outputs in the work folder (and the old Bad_data file) are deleted at the
     start of each call. The original appended to them and skipped re-opening existing block files, so a
     second execution over the first one's leftovers crashed.

Four small data-flow fixes that were required for the unchanged logic to run at all (each marked PHASE0-FIX):
  1. file_list was read back as a 2-D (n, 5) array, so `str(file_list[j])` was a whole row, not a filename
     -> read column 0 only (the file on disk is unchanged).
  2. `Obs.close()` ran at the end of EVERY loop iteration, so the next block write hit a closed file
     (ValueError) -> `Obs.flush()` instead; handles are closed once, in `finally`.
  3. `BD.write(fits_list[i])`: `i` is never defined (NameError on the first corrupt file) -> `filename`.
  4. `pointobs[0]=file_list[j][0]` wrote the first CHARACTER of the filename; every other branch (all marked
     "#same") stores `file_list[j]` -> made identical.

Returns a dict (see end of function); block files are written to base_dir/<observation>/<frequency>/<date>_<n>.txt
and the discarded-file list to base_dir/<observation>/Bad_data_<observation>_<frequency>.txt, as before.
"""

from astropy.io import fits as pyfits
import numpy as np
import array as array
import os
import re
import sys
import shutil
import time
from astropy.time import Time
from scipy.optimize import curve_fit
import datetime

try:
    from clc import load_file as lf
except ImportError:
    # Loaded as a bare module / clc not importable as a package: fall back to the CLI-style flat import.
    _CLC_DIR = os.path.dirname(os.path.abspath(__file__))
    if _CLC_DIR not in sys.path:
        sys.path.append(_CLC_DIR)
    import load_file as lf


#def load_file(filename):
#    """
#    Open fits file, load spectra and extract information
#    relevant to reductions.
#    Returns a dictionary object.
#    """
    #New_file = FE.File_err(filename)
#    hdulist = pyfits.open(filename)

    #print(filename)


#    if hdulist[3].header['TCAL1']:
#           print(hdulist[3].header['TCAL1'])
#           hdulist[3].header['TSYS1'] = hdulist[3].header['TCAL1']
#           hdulist[3].header['TSYSERR1'] = hdulist[3].header['TCALSIG1']
#           hdulist[3].header['TSYS2'] = hdulist[3].header['TCAL2']
#           hdulist[3].header['TSYSERR2'] = hdulist[3].header['TCALSIG2']
#           print(hdulist[3].header['TSYS1'])

#    spectrum = {'Vlsr' : hdulist[2].data['Vlsr'],
#                'LCP'  : hdulist[2].data['Polstate1'],
#                'RCP'  : hdulist[2].data['Polstate4'],
#                'units' : hdulist[2].header['TUNIT2'],
#                'pointing' : hdulist[0].header['SPPOINT'],
#                'position' : hdulist[2].header['POSITION'], 
#                'HPBW' : hdulist[1].header['HPBW'],
#                'date' : hdulist[0].header['DATE'],
#                'object' : hdulist[0].header['OBJECT'],
#                'longitude' : hdulist[0].header['LONGITUD'],
#                'latitude' : hdulist[0].header['LATITUDE'],
#                'Tamb'     : hdulist[0].header['TAMBIENT'],
#                'Humid'    : hdulist[0].header['HUMIDITY'],
#                'Focus' : hdulist[0].header['FOCUS'],
#                'equinox' : hdulist[0].header['EQUINOX'],
#                'bw' : hdulist[0].header['SPBW'],#                
#                'nchan' : hdulist[0].header['SPCHAN'],
#                't_int' : hdulist[0].header['SPTIME'],
#                'fs_offset' : hdulist[0].header['SPFS'],
#                'spVlsr' : hdulist[0].header['SPVLSR'],
#                'restfreq' : hdulist[0].header['RESTFREQ'],
#                'centrefreq' : hdulist[2].header['CENTFREQ'],
#                'Tsys_lcp' : hdulist[3].header['TSYS1'],
#                'DTsys_lcp' : hdulist[3].header['TSYSERR1'],
#                'Tsys_rcp' : hdulist[3].header['TSYS2'],
#                'DTsys_rcp': hdulist[3].header['TSYSERR2'] }
#
    #hdulist.close()
#    return spectrum


def cr8_test(dirname):
    try:
        os.stat(dirname)
    except:
        os.mkdir(dirname)



def run_file_check(observation, frequency, base_dir):
    """Sort FITS files in base_dir/<observation>/<frequency>/ into observation blocks.

    Args:
        observation: source/observation folder name (was the first answer of Interact.interaction()).
        frequency:   frequency folder name (was the second answer of Interact.interaction()).
        base_dir:    folder containing <observation>/<frequency>/ (was the process cwd).

    Returns:
        dict with work_dir, block_files (sorted paths), bad_data_file, num_files.
    """
    Obs = None  # PHASE0-FIX 2: defined up-front so the loop-end flush and the finally-close are safe
    BD = None
    try:
        cwd = os.path.abspath(str(base_dir))
        #print(cwd)
        #os.chdir(cwd) 
        OB, FR = str(observation), str(frequency)

        work_dir = cwd+'/'+OB+'/'+FR+'/'

        def _wd(name):
            """Absolute path of `name` inside work_dir (replaces the old os.chdir(work_dir))."""
            return os.path.join(work_dir, name)

        if not os.path.isdir(work_dir):
            raise FileNotFoundError('File_check work folder not found: %s' % work_dir)
        # Re-run safety: the original appends ('+a') and skips re-opening block files that already exist, so a
        # second run over the first run's leftovers fails. Delete only OUR previous outputs (.txt), never the .fits.
        for _old in os.listdir(work_dir):
            if _old.endswith('.txt'):
                os.remove(_wd(_old))


        with open(_wd('fits_list.txt'), 'w') as _fl:
            for _n in sorted(os.listdir(work_dir)):
                if _n.endswith('.fits') and not _n.startswith('.'):
                    _fl.write(_n + '\n')
        B_D = str('Bad_data_%s_%s.txt' % (OB, FR))
        if os.path.exists(os.path.join(work_dir, "..", B_D)):
            os.remove(os.path.join(work_dir, "..", B_D))  # re-run safety (see above)
        BD=open(os.path.join(work_dir, "..", B_D), "a+")



        fits_list = np.atleast_1d(np.loadtxt(_wd('fits_list.txt'), dtype='str'))

        with open(_wd('%s_%s_file_list.txt' % (OB, FR)), '+a') as Src:
            for filename in fits_list:#range(0, len(fits_list)-1, 1):
        
                try:
        
                   hdulist = pyfits.open(_wd(filename))
                   posi    = str(hdulist[2].header['POSITION'])
                   point   = str(hdulist[0].header['SPPOINT'])
                   SPV     = str(hdulist[2].data['Vlsr'][0])
                   files   = filename#fits_list[i]
           
                   #file_n = lf.load_file(fits_list[i])
                   Obsint  = files[0:8]
                   #posi = str(file_n['position'])
                   #SP   = str(file_n['pointing'])
                   #SPV  = str(file_n['spVlsr'])
           
                   des =' '.join([files, Obsint, posi, point, SPV, "\n"])
                   #des = ' '.join(r)
                   #r2 = "\n"
                   Src.write(des)
                   #Src.write("\n")
           
                except IOError:
                   #print('Empty/Corrupt or incomplete file: %s' % fits_list[i])
                   BD.write(filename)
                   BD.write("\n")
            #hdulist.close()              
        Src.close()

        file_list = np.atleast_1d(np.loadtxt(_wd('%s_%s_file_list.txt' %(OB,FR)), dtype='str', usecols=0))

        num_files = len(file_list)
        #print(spectrum['units'])
        print (num_files)
        P_int1, P_int2, P_int3, P_int4 = 0, 0, 0, 0
        Pcount   = 0
        Ocount   = 0
        ObsCount = 0
        init_ind = 0
        tyds     = 0
        pointobs = [None]*14
        Dates    = []

        #if not os.path.exists('%s_%s_list.txt' %(OB, FR)):
        #    os.system('ls *.fits > fits_list.txt')
        #    file_list = np.atleast_1d(np.loadtxt('fits_list.txt', dtype='str'))



        for j in range(0, num_files, 1):

            file = lf.load_file(_wd(str(file_list[j])))
    
            year=str(file_list[j][0:4])
            dirs=str(file_list[j][0:8])
            position = file['position']
            pointing = file['pointing']
            Dates.append(dirs)
            #if not os.path.exists('%s_%s.txt' %(Dates[0], init_ind)):
            #    Obs=open('%s_%s.txt' %(Dates[0], init_ind), 'w') 
        
          
    
            #cr8_test(cwd+'/'+str(Dates[0]+'_'+str(init_ind))
            if j==num_files-1:
                Dates.append(dirs)
                pointobs.append(file_list[j])
                if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                    Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                for k in range(0,len(pointobs),1):
                    if pointobs[k]!=None:
                        Obs.write(str(pointobs[k]))
                        Obs.write("\n")

                Dates[:] = []
                pointobs =[None]*10
                P_int1, P_int2, P_int3, P_int4 = 0, 0, 0, 0
                Ocount=0
                Pcount=0
    
            elif file['position']=='HPN':

                if P_int1 == 0 and Pcount == 0 and Ocount == 0:
                    Dates.append(dirs)
                    if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                        Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                    #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                    P_int1+=1
                    Pcount+=1
                    pointobs[0]=file_list[j] #pointobs.append if problematic
                    #print(pointobs[0])
                elif P_int1 == 0 and Pcount == 0 and Ocount != 0 and dirs!=Dates[0]:

                    Ocount =0 
                    for k in range(0,len(pointobs),1):
                        if pointobs[k]!=None:
                            Obs.write(str(pointobs[k]))
                            Obs.write("\n")

                    Dates[:] = []
                    pointobs =[None]*14
                    init_ind=0
                    Dates.append(dirs)
                    if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                        Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                    #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                    P_int1=1
                    Pcount+=1
                    pointobs[0]=file_list[j] #same

                elif P_int1 == 0 and Pcount == 0 and Ocount != 0 and dirs==Dates[0]:

                    #Ocount =0 

                    Dates.append(dirs)
                    #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                    P_int1=1
                    Pcount+=1
                    pointobs[0]=file_list[j] #same  

                elif P_int1 ==1 and Pcount < 6 and Ocount == 0:
                    BD.write(str(pointobs[0]))
                    BD.write("\n")
                    pointobs[0]=file_list[j]
                elif P_int1 ==1 and Pcount < 6 and Ocount != 0:
                    BD.write(str(pointobs[0]))
                    BD.write("\n")
                    pointobs[0]=file_list[j] # Ocount if problematic
                elif P_int1 == 1 and Pcount == 6 and dirs!=Dates[0]:
                    if Ocount != 0:
                        Pcount=0
                        #init_ind=0
                        if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                        #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind) )
                        #print(len(pointobs))
                        for k in range(0,len(pointobs),1):
                            if pointobs[k]!= None:
                                 Obs.write(str(pointobs[k]))
                                 Obs.write("\n")

                        init_ind=0
                        Dates[:] = []   
                        pointobs = [None]*14
                        P_int1, P_int2, P_int3, P_int4 = 0, 0, 0, 0
                        Dates.append(dirs)
                        if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                        #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind) )
                        pointobs[0]=file_list[j] # same
                        P_int1=1
                        Pcount+=1

                        Ocount=0

                    elif Ocount==0:

                        Pcount=0
                        if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                        #init_ind=0
                        for k in range(0,len(pointobs),1):
                            if pointobs[k]!=None:
                                Obs.write(str(pointobs[k]))
                                Obs.write("\n")
                        init_ind=0
                        #print Dates[0]
                        Dates[:]=[]   
                        pointobs = [None]*14
                        P_int1, P_int2, P_int3, P_int4 = 0, 0, 0, 0
                        Dates.append(dirs)
                        if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                        #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind) )
                        pointobs[0]=file_list[j] #same
                        P_int1=1
                        Pcount+=1
          
                elif P_int1==1 and Pcount==6 and dirs==Dates[0]:

                    if Ocount!=0:

                        Pcount=0
                        if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                        for k in range(0,len(pointobs),1):
                            if pointobs[k]!=None:
                                Obs.write(str(pointobs[k]))
                                Obs.write("\n")
                        Dates[:] = []   
                        pointobs = [None]*14
                        P_int1, P_int2, P_int3, P_int4 = 0, 0, 0, 0
                        init_ind+=1
                        Dates.append(dirs)
                        if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                        #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                        pointobs[0]=file_list[j] #same
                        P_int1=1
                        Pcount+=1
                        #init_ind=0

                        Ocount=0

                    elif Ocount==0:

                        Pcount=0
                        if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                
                        for k in range(0,len(pointobs),1):
                            if pointobs[k]!=None:
                                Obs.write(str(pointobs[k]))
                                Obs.write("\n")
                        #print Dates[0]
                        Dates[:]=[]   
                        pointobs = [None]*14
                        P_int1, P_int2, P_int3, P_int4 = 0, 0, 0, 0
                        init_ind+=1
                        Dates.append(dirs)
                        if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                        #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                        pointobs[0]=file_list[j] #same
                        P_int1=1
                        Pcount+=1
                        #init_ind=0 
                
            elif file['position']=='HPS' and P_int2==0 and Pcount < 6:
                P_int2 =1
                Pcount +=1
                pointobs[1] = (file_list[j]) #same
        
            elif file['position']=='HPS' and P_int2==1 and Pcount < 6 and Ocount==0:
                BD.write(str(pointobs[1]))
                BD.write("\n")
                #shutil.move(cwd+'/'+pointobs[1],cwd+'/'+'Bad_data')
                pointobs[1]=file_list[j]

            elif file['position']=='HPS' and P_int2==1 and Pcount < 6 and Ocount!=0:
                BD.write(str(pointobs[1]))#shutil.move(cwd+'/'+pointobs[1],cwd+'/'+'Bad_data')
                BD.write("\n")
                pointobs[1]=file_list[j]

            elif file['position']=='HPE' and P_int3==0 and Pcount < 6:
                P_int3 =1
                Pcount +=1
                pointobs[2] =file_list[j] #same

            elif file['position']=='HPE' and P_int3==1 and Pcount < 6 and Ocount==0:
                BD.write(str(pointobs[2]))#shutil.move(cwd+'/'+pointobs[2],cwd+'/'+'Bad_data')
                BD.write("\n")
                pointobs[2]=file_list[j]

            elif file['position']=='HPE' and P_int3==1 and Pcount < 6 and Ocount!=0:
                BD.write(str(pointobs[2]))#shutil.move(cwd+'/'+pointobs[2],cwd+'/'+'Bad_data')
                BD.write("\n")
                pointobs[2]=file_list[j] #same    

            elif file['position']=='HPW' and P_int4==0 and Pcount < 6:
                P_int4 =1
                Pcount +=1
                pointobs[3] = file_list[j] #same

            elif file['position']=='HPW' and P_int4==1 and Pcount < 6 and Ocount==0:
                BD.write(str(pointobs[3]))#shutil.move(cwd+'/'+pointobs[3],cwd+'/'+'Bad_data')
                BD.write("\n")
                pointobs[3]=file_list[j]

            elif file['position']=='HPW' and P_int4==1 and Pcount < 6 and Ocount!=0:
                BD.write(str(pointobs[3]))#shutil.move(cwd+'/'+pointobs[3],cwd+'/'+'Bad_data')
                BD.write("\n")
                pointobs[3]=file_list[j]

            elif (file['position']=='ON' and file['pointing']==1 and Pcount == 4):
                #P_int5 +=1
                Pcount +=1
                pointobs[Pcount-1]=file_list[j] #s
    
            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==1 and Pcount == 5:

                Pcount +=1
                pointobs[Pcount-1]=file_list[j]

            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==0 and Pcount == 6 and dirs==Dates[0]:
                Ocount += 1
                pointobs[6 +(Ocount-1)] =file_list[j] #same

            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==0 and Pcount == 0 and Ocount == 0:
                Ocount += 1
                if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                            Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                pointobs[6 +(Ocount-1)] =file_list[j] #same

                #print pointobs, Dates
            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==0 and Pcount < 6 and Pcount!= 0 and Ocount == 0:

                Ocount += 1

                for k in range(0,5,1):
                    Obs.write(str(pointobs[k]))#shutil.move(cwd+'/'+pointobs[k], cwd+'/'+'Bad_data')
                    Obs.write("\n")

                pointobs =[None]*14
                pointobs[6 +(Ocount-1)] =file_list[j] #same

                #print pointobs, Dates
            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==0 and Pcount==6 and dirs!=Dates[0]:

                Ocount = 0
            ##    #print j, pointobs
                for k in range(0,14,1):
                    if pointobs[k]!=None:
                        Obs.write(str(pointobs[k]))#shutil.move(cwd+'/'+pointobs[k], cwd+'/'+Dates[0]+'_'+str(init_ind))
                        Obs.write("\n")


                Dates[:]=[]
                pointobs =[None]*14
                P_int1, P_int2, P_int3, P_int4 = 0, 0, 0, 0
                Pcount = 0
                Ocount += 1
                Dates.append(dirs)
                if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                    Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                pointobs[6+(Ocount-1)]=file_list[j]
    
            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==0 and Pcount ==0 and dirs==Dates[0]:
                Ocount += 1
                Dates.append(dirs)
                if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                    Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                pointobs[6 + (Ocount-1)]=file_list[j] #same    
                #print (pointobs)
                #time.sleep(1)
            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==0 and Pcount ==0 and dirs!=Dates[0]:
                Ocount = 0

                for k in range(0,14,1):
                    if pointobs[k] != None:
                        Obs.write(str(pointobs[k]))#shutil.move(cwd+'/'+pointobs[k], cwd+'/'+Dates[0]+'_'+str(init_ind))
                        Obs.write("\n")

                init_ind=0
                Dates[:] = []
                pointobs =[None]*14
                Ocount+=1
                Dates.append(dirs)
                if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                    Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                pointobs[6 + (Ocount-1)]=file_list[j] #same

            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==0 and Pcount ==0 and dirs!=Dates[0]:
                Ocount = 0

                for k in range(0,10,1):
                    if pointobs[k] != None:
                        Obs.write(str(pointobs[k]))#shutil.move(cwd+'/'+str(pointobs[k]), cwd+'/'+Dates[0]+'_'+str(init_ind))
                        Obs.write("\n")

            #    init_ind+=1

                Dates[:] = []
                pointobs =[None]*10
                Dates.append(dirs)
                if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                    Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                pointobs[6 + (Ocount-1)]=file_list[j] #same    


                #print pointobs       
            elif (file['position']=='ON' or file['position']=='OFF') and file['pointing']==0 and Pcount==6 and dirs==Dates[0]:
                Ocount = 0

                for k in range(0,len(pointobs),1):
                    if pointobs[k]!=None:
                        Obs.write(str(pointobs[k]))  #shutil.move(cwd+'/'+pointobs[k], cwd+'/'+Dates[0]+'_'+str(init_ind))
                        Obs.write("\n")

                init_ind+=1
                Dates[:]=[]
                pointobs =[None]*14
                P_int1, P_int2, P_int3, P_int4 = 0, 0, 0, 0
                Dates.append(dirs)
                if not os.path.exists(_wd('%s_%s.txt' %(Dates[0], init_ind))):
                    Obs=open(_wd('%s_%s.txt' %(Dates[0], init_ind)), 'w') 
     
                #cr8_test(cwd+'/'+Dates[0]+'_'+str(init_ind))
                Ocount+=1
                pointobs[6 +(Ocount-1)]=file_list[j] #same
                Pcount = 0
    
            if Obs is not None:
                Obs.flush()

        BD.close()                               

        # ---- end of original script body ----
        block_files = sorted(
            os.path.join(work_dir, n) for n in os.listdir(work_dir)
            if n.endswith('.txt') and n not in ('fits_list.txt', '%s_%s_file_list.txt' % (OB, FR))
        )
        return {
            'work_dir': work_dir,
            'block_files': block_files,
            'bad_data_file': os.path.join(cwd, OB, B_D),
            'num_files': num_files,
        }
    finally:
        for _h in (Obs, BD):
            if _h is not None and not _h.closed:
                _h.close()
