import scipy.optimize as opt
import numpy as np
import pylab as plt

def twoD_Gaussian(xy, amplitude, xo, yo, sigma_x, sigma_y, theta, offset):
    x, y = xy
    xo = float(xo)
    yo = float(yo)    
    a = (np.cos(theta)**2)/(2*sigma_x**2) + (np.sin(theta)**2)/(2*sigma_y**2)
    b = -(np.sin(2*theta))/(4*sigma_x**2) + (np.sin(2*theta))/(4*sigma_y**2)
    c = (np.sin(theta)**2)/(2*sigma_x**2) + (np.cos(theta)**2)/(2*sigma_y**2)
    g = offset + amplitude*np.exp( - (a*((x-xo)**2) + 2*b*(x-xo)*(y-yo) + c*((y-yo)**2)))
    return g.ravel()
    
x = np.linspace(-100, 100, 201)
y = np.linspace(-100, 100, 201)
x,y = np.meshgrid(x, y)

#create data
data = twoD_Gaussian((x, y), 3, 0, 0, 10, 10, 0, 10)

# plot twoD_Gaussian data generated above
plt.figure()
plt.imshow(data.reshape(201,201))
plt.colorbar()

# add some noise to the data and try to fit the data generated beforehand
initial_guess = (3,0,0,10,10,0,10)

data_noisy = data + 0.2*np.random.normal(size=data.shape)

popt, pcov = opt.curve_fit(twoD_Gaussian, (x,y), data_noisy, p0 = initial_guess)

data_fitted =twoD_Gaussian((x,y), *popt)
print(popt)
print(pcov)
fig, ax = plt.subplots(1, 1)
#ax.hold(True) For older versions. This has now been deprecated and later removed
ax.imshow(data_noisy.reshape(201, 201), cmap=plt.cm.jet, origin='lower',
    extent=(x.min(), x.max(), y.min(), y.max()))
#ax.contour(x, y, data_fitted.reshape(201, 201), 8, colors='w')
plt.savefig("2D_Gauss.pdf", bbox_inches='tight')


plt.show()
