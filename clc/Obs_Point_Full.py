import Calibrate_PSS_PWR as CPP
import Cal_point_cor as Cpc
import load_file as lf
import Flat_base as Fb
import Baseline as Bl
import plot_spec as PS
import logging
#precip = 0.0

def reduce_point(file_list, file_list2, file_list3, mask, mask2, vll, vrl, Freq, spectra):
    
    """
    Through the years observations of strong maser sources have been made to test the pointing model. 
    For strong maser sources the pointing observations can still be used as a full observation, only using the
    on-source pair of the pointing observations as a on-source integration although the RMS noise will be high.
    """
    Elev_ang = 0
    ATcor = 0
    Az_deg = 0
    tsys_l = 0
    tsys_r = 0
    precip = 0
    if file_list2[5]=='ON':
        print('Frequency-switched')
        logging.info('Frequency-switched')
        #pc, NS_off, EW_off = Cpc.calculate_pointing_corr_freq(file_list, file_list2,file_list3, llim, rlim, peak_vel, half_width, Order, Order2, dirname)
        on_fs1 = lf.load_file(file_list3[4])
        on_fs2 = lf.load_file(file_list3[5])
        new_spec1, new_spec2 = Bl.freq_switch(on_fs1, on_fs2)
        Freq = str(new_spec1['restfreq'])[0:5]   
        tsys_l          = float(new_spec1['Tsys_lcp'])
        tsys_r          = float(new_spec1['Tsys_rcp'])
        
        new_spec1['LCP'], new_spec1['RCP'] = Fb.flatten_baseline(new_spec1['Vlsr'], new_spec1['LCP'], new_spec1['RCP'], vll, vrl, mask, mask2)
        #new_spec1['RCP'] = flatten_baseline(new_spec1['Vlsr'], new_spec1['RCP'], mask2, Order2)
        new_spec2['LCP'], new_spec2['RCP'] = Fb.flatten_baseline(new_spec2['Vlsr'], new_spec2['LCP'], new_spec2['RCP'], vll, vrl, mask, mask2)
        
                    
        nd_lcp, nd_rcp, ATcor, Elev_ang, Az_deg, precip = CPP.PWR(new_spec1['date'], new_spec1['longitude'], new_spec1['latitude'], new_spec1['Tamb'], new_spec1['Humid'], Freq)
        new_spec1['LCP'] = new_spec1['LCP']*nd_lcp*ATcor
        new_spec1['RCP'] = new_spec1['RCP']*nd_rcp*ATcor
        new_spec2['LCP'] = new_spec2['LCP']*nd_lcp*ATcor
        new_spec2['RCP'] = new_spec2['RCP']*nd_rcp*ATcor
        
        spectra.append(new_spec1)
        spectra.append(new_spec1)
        
    elif file_list2[5]=='OFF':            
        print('Position-switched')
        logging.info('Position-switched')
        #pc, NS_off, EW_off = Cpc.calculate_pointing_corr_pos(file_list, file_list2,file_list3, llim, rlim, peak_vel, half_width, Order, Order2, dirname)        
        on_ps = lf.load_file(file_list3[4])
        off_ps = lf.load_file(file_list3[5])
        new_spec = Bl.pos_switch(on_ps, off_ps)
                    
        if Freq=='23694':
                
            new_spec['LCP'][512] = new_spec['LCP'][513]
            new_spec['RCP'][512] = new_spec['RCP'][513]
                
        tsys_l = float(new_spec['Tsys_lcp'])
        tsys_r = float(new_spec['Tsys_rcp'])
        #print(tsys_l, tsys_r)
        new_spec['LCP'], new_spec['RCP'] = Fb.flatten_baseline(new_spec['Vlsr'], new_spec['LCP'], new_spec['RCP'], vll, vrl, mask, mask2)
                
        nd_lcp, nd_rcp, ATcor, Elev_ang, Az_deg, precip = CPP.PWR(new_spec['date'], new_spec['longitude'], new_spec['latitude'], new_spec['Tamb'], new_spec['Humid'], Freq)
        new_spec['LCP'] = new_spec['LCP']*nd_lcp*ATcor
        new_spec['RCP'] = new_spec['RCP']*nd_rcp*ATcor
        
        spectra.append(new_spec)
        
    return spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip
        
    
        
        
def full_point_obs(file_list, file_list2, file_list3, num_full_pairs, full_int_on, mask, mask2, vll, vrl, Freq, spectra):
    
    """
    Here the normal reduction is done on either the full on-source pointing observations or if only on-source
    observations was conducted. 
    """
    
    Elev_ang = 0
    ATcor = 0
    Az_deg = 0
    tsys_l = 0
    tsys_r = 0
    for i in range(num_full_pairs):
            
        if file_list2[full_int_on[i*2+1]]=='ON':
            
            on_fs1 = lf.load_file(file_list3[full_int_on[i*2]])
            on_fs2 = lf.load_file(file_list3[full_int_on[i*2+1]])
            new_spec1, new_spec2 = Bl.freq_switch(on_fs1, on_fs2)
            Freq = str(new_spec1['restfreq'])[0:5]
            new_spec1['LCP'], new_spec1['RCP'] = Fb.flatten_baseline(new_spec1['Vlsr'], new_spec1['LCP'], new_spec1['RCP'], vll, vrl,  mask, mask2)
            #new_spec1['RCP'] = flatten_baseline(new_spec1['Vlsr'], new_spec1['RCP'],  mask2, Order2)
            new_spec2['LCP'], new_spec2['RCP'] = Fb.flatten_baseline(new_spec2['Vlsr'], new_spec2['LCP'], new_spec2['RCP'], vll, vrl,  mask, mask2)
                            
            nd_lcp, nd_rcp, ATcor, Elev_ang, Az_deg, precip = CPP.PWR(new_spec1['date'], new_spec1['longitude'], new_spec1['latitude'], new_spec1['Tamb'], new_spec1['Humid'], Freq)
            new_spec1['LCP'] = new_spec1['LCP']*nd_lcp*ATcor
            new_spec1['RCP'] = new_spec1['RCP']*nd_rcp*ATcor
            new_spec2['LCP'] = new_spec2['LCP']*nd_lcp*ATcor
            new_spec2['RCP'] = new_spec2['RCP']*nd_rcp*ATcor
                
            spectra.append(new_spec1)
            spectra.append(new_spec2)
            tsys_l = float(new_spec1['Tsys_lcp'])
            tsys_r = float(new_spec1['Tsys_rcp'])
            
        elif file_list2[full_int_on[i*2+1]]=='OFF':
            
            on_ps  = lf.load_file(file_list3[full_int_on[i*2]])
            off_ps = lf.load_file(file_list3[full_int_on[i*2+1]])
            
            new_spec = Bl.pos_switch(on_ps, off_ps)
            
            if Freq=='23694':
                
                new_spec['LCP'][512] = new_spec['LCP'][513]
                new_spec['RCP'][512] = new_spec['RCP'][513]
            
                
            tsys_l          = float(new_spec['Tsys_lcp'])
            tsys_r          = float(new_spec['Tsys_rcp'])
            
            #print(tsys_l, tsys_r)
            new_spec['LCP'], new_spec['RCP'] = Fb.flatten_baseline(new_spec['Vlsr'], new_spec['LCP'], new_spec['RCP'], vll, vrl, mask, mask2)
                                    
            nd_lcp, nd_rcp, ATcor, Elev_ang, Az_deg, precip = CPP.PWR(new_spec['date'], new_spec['longitude'], new_spec['latitude'], new_spec['Tamb'], new_spec['Humid'], Freq)
            new_spec['LCP'] = new_spec['LCP']*nd_lcp*ATcor
            new_spec['RCP'] = new_spec['RCP']*nd_rcp*ATcor
            
            spectra.append(new_spec)
                
    return spectra, tsys_l, tsys_r, Elev_ang, Az_deg, ATcor, precip

