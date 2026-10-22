#---------------------------------------------------------------------------------------------#
# Imports
import math
import numpy as np
import logging


from astropy.time import Time
from astropy import units as u
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
#---------------------------------------------------------------------------------------------#

def PSS(Freq, t):
    """
    This function, takes the variables Freq and t (time of observation) as arguments. The time of observation is used to search 
    the database of Point Source Sensitivity (PSS) values to use the PSS values closest to the time of observation. A monthly average 
    around the time of observation is used to calculate an average PSS value for each polarization. Each polarization has it's own 
    file containing thee PSS as function of time.
    
    The Frequency (Freq) is used to choose which file to open to do the above calculation. Each Frequency have its own PSS values.
     
    Currently, the database is written out to a csv file and then ported to a txt file from where it is read for use in the averaging calculations. 
    The final aim of this is to fully automated pull the PSS values from the database. 
    
    """
    #Freq = restfreq[0:5]
    LCP_PSS = 0.0
    RCP_PSS = 0.0
    
    if Freq =='22235':
           
        with open("../../../PSS_22235_Jupiter_LCP.txt", 'r') as MH3_L:
            data1=np.loadtxt(MH3_L,dtype="str") 
            with open("../../../PSS_22235_Jupiter_RCP.txt", 'r') as MH3_R:
                data2=np.loadtxt(MH3_R,dtype="str") 
            LCP_PSS, RCP_PSS = Best_PSS(data1, data2, t)
            
    elif Freq =='20970' or Freq =='20346':
           
        with open("../../../PSS_22235_Jupiter_LCP.txt", 'r') as MH3_L:
            data1=np.loadtxt(MH3_L,dtype="str") 
            with open("../../../PSS_22235_Jupiter_RCP.txt", 'r') as MH3_R:
                data2=np.loadtxt(MH3_R,dtype="str") 
            LCP_PSS, RCP_PSS = Best_PSS(data1, data2, t)

        
    elif Freq =='23121' or Freq=='23694' or Freq =='23722':
        
        with open("../../../PSS_22235_Jupiter_LCP.txt", 'r') as MH3_L:
            data1=np.loadtxt(MH3_L,dtype="str") 
            with open("../../../PSS_22235_Jupiter_RCP.txt", 'r') as MH3_R:
                data2=np.loadtxt(MH3_R,dtype="str") 
            LCP_PSS, RCP_PSS = Best_PSS(data1, data2, t)

        
#        with open("../../../PSS_23695.txt", 'r') as MNH_L:
#            data=np.loadtxt(MNH,dtype="float") 
        
            #LCP_PSS, RCP_PSS = Best_PSS(data, t)
#            LCP_PSS = 10.36
#            RCP_PSS = 10.79
#            print(LCP_PSS,RCP_PSS)
    elif Freq =='12178' or Freq =='12229':
        
        with open("../../../PSS_12178_3C123_LCP.txt", 'r') as MH3_L:
            data1=np.loadtxt(MH3_L,dtype="str") 
            with open("../../../PSS_12178_3C123_RCP.txt", 'r') as MH3_R:
                data2=np.loadtxt(MH3_R,dtype="str") 
            LCP_PSS, RCP_PSS = Best_PSS(data1, data2, t)
       
            #LCP_PSS, RCP_PSS = Best_PSS(data, t)
       #     LCP_PSS = 7.28
       #     RCP_PSS = 7.81
            print(LCP_PSS,RCP_PSS)
    elif Freq =='66685' or Freq =='61811' or Freq =="61810" or Freq =='6708.':
        
        with open("../../../PSS_6668_Hydra_LCP.txt", 'r') as MH3_L:
            data1=np.loadtxt(MH3_L,dtype="str") 
            with open("../../../PSS_6668_Hydra_RCP.txt", 'r') as MH3_R:
                data2=np.loadtxt(MH3_R,dtype="str") 
            LCP_PSS, RCP_PSS = Best_PSS(data1, data2, t)
       #     LCP_PSS = 5.58
       #     RCP_PSS = 4.49
            #print(LCP_PSS, RCP_PSS)
    elif Freq =='48296' or Freq=='46602' or Freq=='47506' or Freq=='47655':
        
        #with open("../../../PSS_4829.txt", 'r') as H2C_L:
        #    data=np.loadtxt(H2C,dtype="float") 
            #LCP_PSS, RCP_PSS = Best_PSS(data, t)

            LCP_PSS = 5.58
            RCP_PSS = 4.49
            print(LCP_PSS,RCP_PSS)
        
    elif Freq =='16654' or Freq == '16673' or Freq == '1612' or Freq == '17205':
        
        #with open("../../../PSS_OH.txt", 'r') as OH_L:
        #    data1=np.loadtxt(OH,dtype="float") 
        #    with open("../../../PSS_OH.txt", 'r') as OH_R:
        #        data2=np.loadtxt(OH,dtype="float") 
            #LCP_PSS, RCP_PSS = Best_PSS(data, t)
            LCP_PSS = 5.1
            RCP_PSS = 5.1
            print(LCP_PSS,RCP_PSS)
    
    #print("This is rediculous")
    return LCP_PSS, RCP_PSS
    
def Best_PSS(data1, data2, t):
    """
    This function is used in the calculation of the average PSS value. The function takes the 
    LCP and RCP data and the observing time as input. It tests where in the data-file (in time) 
    the observation is located. These files will be kept up-to-date as well as possible. However, 
    an observation that is before the first PSS value or after the last PSS value, will use either 
    the first month's average or the last month's average as the representative PSS value. Otherwise the 
    average is calculated 15 days on either side of the observing time.
    """
    
    PS_LCP = 0
    PS_RCP = 0
    k = 0
    s = 0
    g = 0
    f = 0
    p = 0
    o = 0
    Time_L      = np.delete(data1[:,0],0).astype(float)
    Time_R      = np.delete(data2[:,0],0).astype(float)
    P_LCP       = np.delete(data1[:,2],0).astype(float)
    P_RCP       = np.delete(data2[:,2],0).astype(float)
    
    #P_LCP_D     = data[:,2].astype(float)
    #P_RCP_D     = data[:,3].astype(float)
    print(t)
    len_L = len(Time_L)-1
    len_R = len(Time_R)-1
    #print(np.where(np.logical_and(Time_L//t==0, Time_L//t==1)))
    
    for j in range(1, len_L, 1):
        
        #if Time_L[j]-t > -2 and Time_L[j+1]-t < 2 and (len(Time_L)-j > 15):
         #   print(t, Time_L[j], Time_L[j+1])
        #print(np.where(np.logical_and(Time_L[j]//t==0, Time_L[j+1]//t==1)))
        if (Time_L[j-1]//(t)==0) and (Time_L[j]//(t)==1) and (len_L-j > 30):
            #print(np.where(np.logical_and(Time_L[j]//t==0, Time_L[j+1]//t==1)))
                 
            for q in range(j-50, len_L, 1):
                
                if Time_L[q]//(t-15)==0 and Time_L[q+1]//(t-15)==1:
                    #print(Time_L[q])
                    k = q+1
                    #print(k, "LCP S")
                    
                if Time_L[q]//(t+15)==0 and Time_L[q+1]//(t+15)==1: 
                
                    s = q
                    
                if (Time_L[q+1] - Time_L[q]) > 10: 
                 
                    s = q
                    #print(s, "LCP T")
        
        elif (Time_L[0] > t):
            
            k = 0
            for q in range(0, 30, 1):
                
                if Time_L[q]//(Time_L[0]+30)==0 and Time_L[q+1]//(Time_L[0]+30)==1:
                
                    s = q
                    #print(s, "LCP T")
        
        elif (Time_L[len_L] < t) or (Time_L[len_L] > t and Time_L[len_L-1] < t):
            #print(Time_L[j], Time_L[len_L])
            s = len_L
            for q in range(len_L-50, len_L-1, 1):
                
                if Time_L[q]//(Time_L[len_L]-30)==0 and Time_L[q+1]//(Time_L[len_L]-30)==1:
                
                    k = q
                    #print(s, "LCP T")
        
                    
                
            
            
        elif (Time_L[j-1]//t==0) and (Time_L[j]//t==1) and (len_L-j < 30):
            print(Time_L[j], Time_L[len_L])
            s = len_L
            for q in range(len_L-50, len_L-1, 1):
                #print(q, Time_L[q], Time_L[q]//(t-15), t-15, Time_L[q+1], Time_L[q]//(t-14), t-14)
                if Time_L[q]//(t-30)==0 and Time_L[q+1]//(t-30)==1:
                    #print(Time_L[q])
                    k = q+1
                    #print(k, "LCP S")
                #if Time_L[q]//t == 0 and Time_L[q+1]//t ==1 and Time_L[len_L-1]-t<5:
                    
                #    s = len_L
                #print(s, "LCP T")
            
                        
        elif (Time_L[j-1]//t==0) and (Time_L[j]//t==1) and (Time_L[j] - (t - 15) < 0):
            
            for q in range(0, 30, 1):
                
                if Time_L[q]//(t-15)==0 and Time_L[q+1]//(t-15)==1:
                    #print(Time_L[q])
                    k = q+1
                    #print(k, "LCP S")
                    
                else:
                    k = 0
                    #print(k, "LCP S")
                    
                if Time_L[q]//(t+15)==0 and Time_L[q+1]//(t+15)==1:
                
                    s = q
        
        
            #k = np.where(np.logical_and(Time_L[j-1]//t==0, Time_L[j]//t==1))
            #s = np.where(np.logical_and(Time_L//(t+29)==0, Time_L//(t+30)==1)) 
            
    #r = s-k
    print(k, s)
 #------------------------------------------------------------------------------------------------   
    for w in range(1, len_R, 1):
        
        if (Time_R[w-1]//t==0) and (Time_R[w]//t==1) and (len_R-w > 30):
            #print(np.where(np.logical_and(Time_R[w]//t==0, Time_R[w+1]//t==1)))
            #print("True 1")
            for q in range(w-50, len(Time_R)-1, 1):
                #print(q)
                #print(q, Time_L[q], Time_L[q]//(t-15), t-15, Time_L[q+1], Time_L[q]//(t-14), t-14)
                if Time_R[q]//(t-15)==0 and Time_R[q+1]//(t-15)==1:
                    #print(Time_L[q])
                    g = q+1
                    #print(g, "RCP S")
                    
                if Time_R[q]//(t+15)==0 and Time_R[q+1]//(t+15)==1:
                
                    f = q
                    
                if (Time_R[q+1] - Time_R[q]) > 10: 
                 
                    f = q
                
                #if Time_R[q]//(t+15)==1 and Time_R[q+1]//(t+15)==1:
                
                #    f = q-1
        
        elif (Time_R[0] > t):
            #print("True 2")
            g = 0
            for q in range(0, 30, 1):
                
                if Time_R[q]//(Time_R[0]+30)==0 and Time_R[q+1]//(Time_R[0]+30)==1:
                
                    f = q
                    
        elif (Time_R[len_R] < t) or (Time_R[len_R] > t and Time_R[len_R-1] < t):
            #print("True 3")
            f = len_R
            for q in range(len_R-50, len_R-1, 1):
                
                if Time_R[q]//(Time_R[len_R]-30)==0 and Time_R[q+1]//(Time_R[len_R]-30)==1:
                
                    g = q
                    #print(s, "RCP S ")
        
        #print(f, "RCP T")
            
        elif (Time_R[w-1]//t==0) and (Time_R[w]//t==1) and (len_R-w < 30):
            #print("True 4")
            for q in range(len_R-31, len_R-1, 1):
                #print(q, Time_L[q], Time_L[q]//(t-15), t-15, Time_L[q+1], Time_L[q]//(t-14), t-14)
                if Time_R[q]//(t-30)==0 and Time_R[q+1]//(t-30)==1:
                    #print(Time_L[q])
                    g = q+1
                    #print(g, "RCP S")
                    
                
                
            f = len_R
                #print(f, "RCP T")
        
                   
        elif (Time_R[w-1]//t==0) and (Time_R[w]//t==1) and (Time_R[w] - (t - 15) < 0):
            print("True 5")
            for q in range(0, 30, 1):
                #print(q, Time_L[q], Time_L[q]//(t-15), t-15, Time_L[q+1], Time_L[q]//(t-14), t-14)
                if Time_R[q]//(t-15)==0 and Time_R[q+1]//(t-15)==1:
                    #print(Time_L[q])
                    g = q+1
                    #print(g, "RCP S")
                
                else:
                    g = 0
                    #print(g, "RCP S")
                    
                if Time_R[q]//(t+15)==0 and Time_R[q+1]//(t+15)==1:
                
                    f = q
        
        
    #print(g, f)
    p = 0
    o = 0
    
    for a in range(k, s, 1):
        
        p += 1
        PS_LCP += P_LCP[a]
        #PS_RCP += P_RCP[y]
        
    for b in range(g, f, 1):
        
        o += 1
        #PS_LCP += P_LCP[y]
        PS_RCP += P_RCP[b]    
    print(p, o)
    print(s-k, f-g)
    #print(P_LCP[k:s])
    #print(P_RCP[g:f])
    AV_PS_LCP = PS_LCP/p
    AV_PS_RCP = PS_RCP/o
    print(AV_PS_LCP, AV_PS_RCP)
    return AV_PS_LCP, AV_PS_RCP
    
           
def PWR(t, longi, lati, temp, humid, Freq, return_optical_depth=False):
    """
    The affect of attenuation in the atmosphere at higher frequencies is a very important issue to obtain
    accurate measurements. Here the position of the Telescope on Earth together with the observation time 
    is used to calculate the elevation angle and the Azimuth angle of the Telescope at the time of observation. With the elevation 
    angle and the precipitable water vapour through the atmosphere at the given frequency, the attenuation is
    corrected for with a atmospheric correction factor based on the formulas in Meeks et al. page 175)
    """
    Elev_SRC2 = 0
    SRC2_deg = 0
    
    Local_coord = SkyCoord(ra=longi*u.degree, dec=lati*u.degree, frame='fk5', equinox="J1950")
    
    Hartebeesthoek = EarthLocation(lat=-25.8897515*u.deg, lon=27.6853931*u.deg, height=1415.7*u.m)
    utcoffset = 2*u.hour  # Eastern Daylight Time
    
    Local_time = Time(t)# + utcoffset
    
    Elev=Local_coord.transform_to(AltAz(obstime=Local_time,location=Hartebeesthoek)).alt
    Elev2=Local_coord.transform_to(AltAz(obstime=Local_time,location=Hartebeesthoek)).az
    Elev_SRC = str(Elev)
    Elev_SRC2 =str(Elev2)
    
    if Elev_SRC[1]=='d':
        
        SRC_deg = float(Elev_SRC[0:1]) + float(Elev_SRC[2:4])/60 + float(Elev_SRC[5:-1])/(60*60)
    
    elif Elev_SRC[2]=='d':
        
        SRC_deg = float(Elev_SRC[0:2]) + float(Elev_SRC[3:5])/60 + float(Elev_SRC[6:-1])/(60*60)    
    
    
    if Elev_SRC2[2]=='d':
        
        SRC2_deg = float(Elev_SRC2[0:2]) + float(Elev_SRC2[3:5])/60 + float(Elev_SRC2[6:-1])/(60*60)
    
    elif Elev_SRC2[3]=='d':
        
        SRC2_deg = float(Elev_SRC2[0:3]) + float(Elev_SRC2[4:6])/60 + float(Elev_SRC2[7:-1])/(60*60)
        
        
    #print(SRC_deg)
    Zdeg = 90.0-SRC_deg
    Zrad = Zdeg*math.pi/180.0
    Sec_z = 1.0/math.cos(Zrad)
    #def 
    Elev_ang = SRC_deg
    Az_deg   = SRC2_deg
    
    print(temp)      
    precip_WV    = max(0.0, 4.39*humid/100.0/temp*math.exp(26.23-5416/temp))
    sat_vap_pres = 0.611*math.exp(17.27*(temp-273.13)/(temp-273.13+237.3))
    print(sat_vap_pres)
    
    amb_vap_pres = sat_vap_pres*humid/100.0
    if amb_vap_pres < 0:
    
       amb_vap_pres = np.abs(amb_vap_pres)
       print("The ambient vapour pressure was negative")
    else:
      
       amb_vap_pres = amb_vap_pres
          
    print(amb_vap_pres)
    dew_vap_temp = (116.9+237.3*math.log(amb_vap_pres))/(16.78-math.log(amb_vap_pres))
    print(dew_vap_temp)
    WV_dens      = max(0.0, 2164*amb_vap_pres/temp)
    
    #print("Derived precipitable water vapour, %5.5f, mm, \n" % precip_WV)
    
    # The following calculations determines the zenith optical depths
    tau10  = 0.0071+0.00021*precip_WV
    tau15  = (0.055+0.004*WV_dens)/4.343
    tau221 = 0.0140+0.00780*precip_WV
    tau222 = (0.110+0.048*WV_dens)/4.343
    
    #Zenith angle correction 
    
    x_z = -0.0045 +1.00672*Sec_z - 0.002234*Sec_z*Sec_z - 0.0006247*Sec_z*Sec_z*Sec_z
    #print("# =================================================================================== #")
    #print("# The derived precipitable water vapour (PWV) is: \033[42m %2.3f mm \033[0m" % precip_WV)
    #print("# =================================================================================== #")
    #print("# The Zenith angle correction is:\033[42m %1.3f \033[0m , and the Telescope is pointed " % (x_z))
    #print("# =================================================================================== #")
    #print("# to an Elevation angle of: \033[42m %1.3f \033[0m deg, and an Azimuth angle of \033[42m %1.3f \033[0m deg \n" %(Elev_ang, Az_deg))
    #print("# =============================================================================================== #")
    print("# =================================================================================== #")
    print("# The derived precipitable water vapour (PWV) is: %2.3f mm " % precip_WV)
    print("# =================================================================================== #")
    print("# The Zenith angle correction is:%1.3f, and the Telescope is pointed " % (x_z))
    print("# =================================================================================== #")
    print("# to an Elevation angle of: %1.3f deg, and an Azimuth angle of %1.3f deg \n" %(Elev_ang, Az_deg))
    print("# =============================================================================================== #")
    logging.info("# =================================================================================== #")
    logging.info("# The derived precipitable water vapour (PWV) is: %2.3f mm " % precip_WV)
    logging.info("# =================================================================================== #")
    logging.info("# The Zenith angle correction is:%1.3f, and the Telescope is pointed " % (x_z))
    logging.info("# =================================================================================== #")
    logging.info("# to an Elevation angle of: %1.3f deg, and an Azimuth angle of %1.3f deg \n" %(Elev_ang, Az_deg))
    logging.info("# =============================================================================================== #")


    tau10  = tau10*x_z
    tau15  = tau15*x_z
    tau221 = tau221*x_z
    tau222 = tau222*x_z
    #print("# =================================================================================== #")
    #print("# The zenith optical depth for 10GHz is: \033[42m%2.3f\033[0m " % tau10                             )
    #print("# The zenith optical depth for 15GHz is: \033[42m%2.3f\033[0m " % tau15                             ) 
    #print("# The zenith optical depth for 22.2GHz is: \033[42m%1.3f\033[0m " % tau222)
    print("# =================================================================================== #")
    print("# The zenith optical depth for 10GHz is: %2.3f " % tau10                             )
    print("# The zenith optical depth for 15GHz is: %2.3f" % tau15                             ) 
    print("# The zenith optical depth for 22.2GHz is: %1.3f " % tau222)
    print("# =================================================================================== #")
    logging.info("# =================================================================================== #")
    logging.info("# The zenith optical depth for 10GHz is: %2.3f " % tau10                             )
    logging.info("# The zenith optical depth for 15GHz is: %2.3f" % tau15                             ) 
    logging.info("# The zenith optical depth for 22.2GHz is: %1.3f " % tau222)
    logging.info("# =================================================================================== #")
    
    
    #print(tau222)
    #correction for atmospheric absorption
    atcor10 = math.exp(tau10)
    atcor15 = math.exp(tau15)
    atcor221= math.exp(tau221)
    atcor222= math.exp(tau222)
    opT_C = [atcor10, atcor15, atcor221, atcor222]
    
    if Freq=='66685':
        atcor222 = 1.0
    elif Freq=='12178':
        atcor222 = 1.0
    elif Freq=='1665' or Freq=='1667' or Freq=='4829' or Freq=='6030' or Freq=='6035' or Freq=='1720' or Freq=='1612':
        atcor222 = 1.0
    #print("# The atmospheric correction factor for 10GHz is: \033[42m%1.4f\033[0m " % atcor10)
    #print("# The atmospheric correction factor for 15GHz is: \033[42m%1.4f\033[0m " % atcor15)
    #print("# The atmospheric correction factor for 22.2GHz is: \033[42m%1.4f\033[0m " % atcor222)
    #print("# =================================================================================== #")
    print("# The atmospheric correction factor for 10GHz is: %1.4f " % atcor10)
    print("# The atmospheric correction factor for 15GHz is: %1.4f " % atcor15)
    print("# The atmospheric correction factor for 22.2GHz is: %1.4f " % atcor222)
    print("# =================================================================================== #")
    logging.info("# The atmospheric correction factor for 10GHz is: %1.4f " % atcor10)
    logging.info("# The atmospheric correction factor for 15GHz is: %1.4f " % atcor15)
    logging.info("# The atmospheric correction factor for 22.2GHz is: %1.4f " % atcor222)
    logging.info("# =================================================================================== #")
    
    # Brightness temperature of atmosphere at ZA
    tbatmos221 = 260.0*(1 - math.exp(-tau221))
    tbatmos222 = 260.0*(1 - math.exp(-tau222))
    nd_lcp = 1.00
    nd_rcp = 1.00
    if return_optical_depth:
        return nd_lcp, nd_rcp, atcor222, SRC_deg, SRC2_deg, precip_WV, tau222
    return nd_lcp, nd_rcp, atcor222, SRC_deg, SRC2_deg, precip_WV
    
    