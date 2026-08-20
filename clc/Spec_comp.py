def Spec_comp(Vlsr, Amp, half_width):
    """
    First attempt to automatically do Gaussian fitting on a spectrum
    It will iterate and subtract a single gaussian at a time, and test each times what the residual is. 
    It will do a statistical test on the residual to see how close to the rms noise the subtracted spectrum is each time. 
    """
    #plt.plot(Vlsr, Amp, 'r')
    #plt.show()
    
    Id = max(Amp)
    Vind = np.where(Amp[:]==Id)
    Vd = Vlsr[Vind]
    np.random.seed(0)
    x = Vlsr
    y = Amp
    spectrum = Spectrum1D(flux=y*u.Jy, spectral_axis=x*u.um)#*u.Jy #u.um
    # Fit the spectrum and calculate the fitted flux values (``y_fit``)
    g_init = models.Gaussian1D(amplitude=Id*u.Jy, mean=Vd*u.um, stddev=0.5*u.um)
    g_fit = fit_lines(spectrum, g_init)
    y_fit = g_fit(x*u.um)
    Sub_spec = y*u.Jy - y_fit
    
        
    Id2 = max(Sub_spec)
    Vind2 = np.where(Sub_spec[:]==Id2)
    Vd2 = Vlsr[Vind2]
    print (Id2)
    spectrum2 = Spectrum1D(flux=Sub_spec, spectral_axis=x*u.um)#*u.Jy #u.um
    # Fit the spectrum and calculate the fitted flux values (``y_fit``)
    g_init2 = models.Gaussian1D(amplitude=Id2, mean=Vd2*u.um, stddev=0.5*u.um)
    g_fit2 = fit_lines(spectrum2, g_init2)
    y_fit2 = g_fit2(x*u.um)
    Sub_spec2 = Sub_spec - y_fit2
    
    Id3 = max(Sub_spec2)
    Vind3 = np.where(Sub_spec2[:]==Id3)
    Vd3 = Vlsr[Vind3]
        
    spectrum3 = Spectrum1D(flux=Sub_spec2, spectral_axis=x*u.um)#*u.Jy #u.um
    # Fit the spectrum and calculate the fitted flux values (``y_fit``)
    g_init3 = models.Gaussian1D(amplitude=Id3, mean=Vd3*u.um, stddev=0.5*u.um)
    g_fit3 = fit_lines(spectrum3, g_init3)
    y_fit3 = g_fit3(x*u.um)
    Sub_spec3 = Sub_spec2 - y_fit3
    #print (g_init, g_init2)
    #Id2 = max(Sub_spec)
    #Vind2 = np.where(Sub_spec[:]==Id2)
    #Vd2 = Vlsr[Vind2]
    #print (Id2, Vind2, Vd2)
      
    #spectrum2 = Spectrum1D(flux=Sub_spec*u.Jy, spectral_axis=x*u.um)#*u.Jy #u.um
    
    #g_init2 = models.Gaussian1D(amplitude=Id2*u.Jy, mean=Vd2*u.um, stddev=1.*u.um)
    #g_fit2 = fit_lines(spectrum2, g_init2)
    #y_fit2 = g_fit2(x*u.um)
     
    # Plot the original spectrum and the fitted.
    plt.plot(x, y)
    plt.plot(x, y_fit)
    plt.plot(x, Sub_spec, 'b')
    plt.plot(x, Sub_spec2, 'r')
    plt.plot(x, Sub_spec3, 'k')
    plt.ylim(-10,150)
    #plt.plot(x, y*u.Jy-y_fit-y_fit2, 'ko')
    plt.title('Single fit peak')
    plt.grid(True)
    #plt.legend('Original Spectrum', 'Specutils Fit Result')
    #plt.show()