#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Dec 30 12:02:12 2018

ppdire - Projection pursuit dimension reduction

@author: Sven Serneels (Ponalytics)
"""


#from .dicomo import dicomo
import numpy as np
from statsmodels.regression.quantile_regression import QuantReg
import scipy.stats as sps
from scipy.linalg import pinv2
import copy
from sklearn.utils.metaestimators import _BaseComposition
from sklearn.base import RegressorMixin,BaseEstimator,TransformerMixin
from sklearn.utils.extmath import svd_flip
from sprm import rm, robcent
from sprm._m_support_functions import MyException
import warnings

class MyException(Exception):
        pass

class ppdire(_BaseComposition,BaseEstimator,TransformerMixin,RegressorMixin):
    
    """
    PPDIRE Projection Pursuit Dimension Reduction
    
    The projection pursuit algorithm implemented here is the grid algorithm, 
    first outlined in: 
        
        Filzmoser, P., Serneels, S., Croux, C. and Van Espen, P.J., 
        Robust multivariate methods: The projection pursuit approach,
        in: From Data and Information Analysis to Knowledge Engineering,
        Spiliopoulou, M., Kruse, R., Borgelt, C., Nuernberger, A. and Gaul, W., eds., 
        Springer Verlag, Berlin, Germany,
        2006, pages 270--277.
        
    Input parameters to class: 
        projection_index: function or class. dicomo and capi supplied in this
            package can both be used, but user defined projection indices can 
            be processed 
        pi_arguments: dict of arguments to be passed on to projection index 
        n_components: int 
        trimming: float, trimming percentage to be entered as pct/100 
        alpha: float. Continuum coefficient. Only relevant if ppdire is used to 
            estimate (classical or robust) continuum regression 
        center: str, how to center the data. options accepted are options from
            sprm.robcent 
        center_data: bool 
        scale_data: bool. Note: if set to False, convergence to correct optimum 
            is not a given. Will throw a warning. 
        whiten_data: bool. Typically used for ICA (kurtosis as PI)
        square_pi: bool. Whether to square the projection index upon evaluation. 
        copy: bool. Whether to make a deep copy of the input data or not. 
        verbose: bool. Set to True prints the iteration number. 
        return_scaling_object: bool. 
        
    The 'fit' function will take a set of optional input arguments. 
    
    """

    def __init__(self,
                 projection_index, 
                 pi_arguments = {}, 
                 n_components = 1, 
                 trimming = 0,
                 alpha = 1,
                 center = 'mean',
                 center_data=True,
                 scale_data=True,
                 whiten_data=False,
                 square_pi = False,
                 copy=True,
                 verbose=True,
                 return_scaling_object=True):
        # Called arguments
        self.projection_index = projection_index
        self.pi_arguments = pi_arguments
        self.n_components = n_components
        self.trimming = trimming
        self.alpha = alpha
        self.center = center
        self.center_data = center_data
        self.scale_data = scale_data
        self.whiten_data = whiten_data
        self.square_pi = square_pi
        self.copy = copy
        self.verbose = verbose
        self.return_scaling_object = return_scaling_object
        
        # Other global parameters 
        self.constraint = 'norm'
        self.optrange = (-1,1)
        self.licenter = ['mean','median']
        if not(self.center in self.licenter):
            raise(ValueError('Only location estimator classes allowed are: "mean", "median"'))
            
            
    def _gridplane(self,X,pi_arguments={},**kwargs):

        """
        Function for grid search in a plane in two dimensions
        
        Required: X, np.matrix(n,2), data 
        
        Optional keyword arguments: 
            
            y, np.matrix(n,1), second block of data 
            ndir, int, number of directions to scan 
            biascorr, to apply bias correction at normal distribution 
            
        pi_arguments is a dict of arguments passed on to the projection index
            
        Values: 
            wi, np.matrix(p,1): optimal direction 
            maximo, float: optimal value of projection index
            
        Note: this function is writte to be called from within the ppdire class
        
        """
        
                
        if (('biascorr' not in kwargs) and ('biascorr' not in pi_arguments)):
            biascorr = False
        else:
            biascorr = kwargs.get('biascorr')
            
        if (('ndir' not in kwargs) and ('ndir' not in pi_arguments)):
            ndir = 100
        else:
            ndir = kwargs.get('ndir')
            
        if len(pi_arguments) == 0:
            
            pi_arguments = {
                            'alpha': self.alpha,
                            'ndir': ndir,
                            'trimming': self.trimming,
                            'biascorr': biascorr, 
                            'dmetric' : 'euclidean'
                            }
        else:
            pi_arguments['alpha'] = self.alpha
            pi_arguments['trimming'] = self.trimming
            
        if ('y' in kwargs):
            y = kwargs.pop('y')
            pi_arguments['y'] = y
            
        optmax = kwargs.pop('optmax',self.optrange[1])
        
        alphamat = kwargs.pop('alphamat',None)
        if (alphamat != None).all():
            optrange = np.sign(self.optrange)
            stop0s = np.arcsin(optrange[0])
            stop1s = np.arcsin(optrange[1])
            stop1c = np.arccos(optrange[0])
            stop0c = np.arccos(optrange[1])
            anglestart = max(stop0c,stop0s)
            anglestop = max(stop1c,stop1s)
            nangle = np.linspace(anglestart,anglestop,ndir,endpoint=False)            
            alphamat = np.matrix([np.cos(nangle), np.sin(nangle)])
            if optmax != 1:
                alphamat *= optmax
        
        tj = X*alphamat
        if self.square_pi:
            meas = [self.most.fit(tj[:,i],**pi_arguments)**2 
            for i in np.arange(0,ndir)]
        else:
            meas = [self.most.fit(tj[:,i],**pi_arguments) 
            for i in np.arange(0,ndir)]
            
        maximo = np.max(meas)
        indmax = np.where(meas == maximo)[0]
        if len(indmax)>0:
            indmax = indmax[0]
        wi = alphamat[:,indmax]
        
        if (alphamat != None).all():
            setattr(self,'_stop0c',stop0c)
            setattr(self,'_stop0s',stop0s)
            setattr(self,'_stop1c',stop1c)
            setattr(self,'_stop1s',stop1s)
            setattr(self,'optmax',optmax)
        
        return(wi,maximo)
        
        
    
    def _gridplane_2(self,X,q,div,pi_arguments={},**kwargs):
    
        """
        Function for refining a grid search in a plane in two dimensions
        
        Required: X, np.matrix(n,2), data 
                  q, np.matrix(1,1), last obtained suboptimal direction component
                  div, float, number of subsegments to divide angle into
        
        Optional keyword arguments: 
            
            y, np.matrix(n,1), second block of data 
            ndir, int, number of directions to scan 
            biascorr, to apply bias correction at normal distribution 
            
        pi_arguments is a dict of arguments passed on to the projection index
            
        Values: 
            wi, np.matrix(p,1): optimal direction 
            maximo, float: optimal value of projection index
            
        Note: this function is writte to be called from within the ppdire class
        
        """
                
        if (('biascorr' not in kwargs) and ('biascorr' not in pi_arguments)):
            biascorr = False
        else:
            biascorr = kwargs.get('biascorr')
                
        if (('ndir' not in kwargs) and ('ndir' not in pi_arguments)):
            ndir = 100
        else:
            ndir = kwargs.get('ndir')
            
        if len(pi_arguments) == 0:
            
            pi_arguments = {
                            'alpha': self.alpha,
                            'ndir': ndir,
                            'trimming': self.trimming,
                            'biascorr': biascorr, 
                            'dmetric' : 'euclidean'
                            }
        else:
            pi_arguments['alpha'] = self.alpha
            pi_arguments['trimming'] = self.trimming
            
        if 'y' in kwargs:
            y = kwargs.pop('y')
            pi_arguments['y'] = y
    
        optmax = kwargs.pop('optmax',self.optrange[1])
       
        alphamat = kwargs.pop('alphamat',None)
        if (alphamat != None).all():
            anglestart = min(self._stop0c,self._stop0s)
            anglestop = min(self._stop1c,self._stop1s)
            nangle = np.linspace(anglestart,anglestop,ndir,endpoint=True)
            alphamat = np.matrix([np.cos(nangle), np.sin(nangle)])
            if self.optmax != 1:
                alphamat *= self.optmax
        alpha1 = alphamat
        divisor = np.sqrt(1 + 2*np.multiply(alphamat[0,:],alphamat[1,:])*q[0])
        alpha1 = np.divide(alphamat,np.repeat(divisor,2,0))
        tj = X*alpha1
        
        if self.square_pi:
            meas = [self.most.fit(tj[:,i],**pi_arguments)**2 
            for i in np.arange(0,ndir)]
        else:
            meas = [self.most.fit(tj[:,i],**pi_arguments) 
            for i in np.arange(0,ndir)]

        maximo = np.max(meas)
        indmax = np.where(meas == maximo)[0]
        if len(indmax)>0:
            indmax = indmax[0]
        wi = alpha1[:,indmax]
        
        return(wi,maximo)
    
    

    def fit(self,X,*args,**kwargs):
        
        """
        Fit a projection pursuit dimension reduction model. 
        
        Required input argument: X data as matrix or data frame 
        
        Optinal input arguments: 
            
            arg or kwarg:
            y data as vector or 1D matrix
            
            kwargs: 
            h, int: option to overrule class's n_components parameter in fit. 
                Convenient command line, yet should not be used in automated 
                loops, e.g. cross-validation.
                
            dmetric, str: distance metric used internally. Defaults to 'euclidean'
            
            ndir, int: number of directions to compute in grid planes. Increases 
                precision of the solution when higher, yet computes longer. 
                
            maxiter, int: maximal number of iterations to calculate 
            
            compression, bool: whether to use SVD data compression for flat data 
                tables (p > n)
            
            mixing, bool: to estimate mixing matrix (only relevant for ICA)
            
            kwargs only relevant if y specified: 
            regopt, str: regression option for regression step y~T. Can be set
                to 'OLS' (default), 'robust' (will run sprm.rm) or 'quantile' 
                (statsmodels.regression.quantreg). Further parameters to these methods
                can be passed on as well as kwargs, e.g. quantile=0.8. 
        
        """

        # Collect optional fit arguments
        biascorr = kwargs.pop('biascorr',False)
            
        if 'h' not in kwargs:
            h = self.n_components
        else:
            h = kwargs.pop('h')
            self.n_components = h
            
        if 'dmetric' not in kwargs:
            dmetric = 'euclidean'
        else:
            dmetric = kwargs.get('dmetric')
            
        if 'ndir' not in kwargs:
            ndir = 1000
        else:
            ndir = kwargs.get('ndir')
            
        if 'maxiter' not in kwargs:
            maxiter = 10000
        else:
            maxiter = kwargs.get('maxiter')
            
        if 'compression' not in kwargs:
            compression = False
        else:
            compression = kwargs.get('compression')
            
        if 'mixing' not in kwargs:
            mixing = False
        else:
            mixing = kwargs.get('mixing')
            
        if 'y' not in kwargs:
            na = len(args)
            if na > 0: #Use of *args makes it sklearn consistent
                flag = 'two-block'
                y = args[0]
                regopt = kwargs.pop('regopt','OLS')
            else:
                flag = 'one-block'
                y = 0 # to allow calls with 'y=y' in spit of no real y argument present
        else:
            flag = 'two-block'
            y = kwargs.get('y')
            
            regopt = kwargs.pop('regopt','OLS')
                
            if 'quantile' not in kwargs:
                quantile = .5
            else:
                quantile = kwargs.get('quantile')
                
            if regopt == 'robust':
            
                if 'fun' not in kwargs:
                    fun = 'Hampel'
                else:
                    fun = kwargs.get('fun')
                
                if 'probp1' not in kwargs:
                    probp1 = 0.95
                else:
                    probp1 = kwargs.get('probp1')
                
                if 'probp2' not in kwargs:
                    probp2 = 0.975
                else:
                    probp2 = kwargs.get('probp2')
                
                if 'probp3' not in kwargs:
                    probp3 = 0.99
                else:
                    probp3 = kwargs.get('probp3')

            
        if self.projection_index == dicomo:
            
            if self.pi_arguments['mode'] in ('M3','cos','cok'):
            
                if 'option' not in kwargs:
                    option = 1
                else:
                    option = kwargs.get('option')
                
                if option > 3:
                    print('Option value >3 will compute results, but meaning may be questionable')
                
        # Initiate projection index    
        self.most = self.projection_index(**self.pi_arguments)         
        
        # Initiate some parameters and data frames
        if self.copy:
            X0 = copy.deepcopy(X)
            self.X0 = X0
        else:
            X0 = X        
        X0 = np.array(X0).astype('float64')    
        n,p = X.shape 
        trimming = self.trimming
        
        # Check dimensions 
        if h > min(n,p):
            raise(MyException('number of components cannot exceed number of samples'))
            
        if (self.projection_index == dicomo and self.pi_arguments['mode'] == 'kurt' and self.whiten_data==False):
            warnings.warn('Whitening step is recommended for ICA')
            
        # Pre-processing adjustment if whitening
        if self.whiten_data:
            self.center_data = True
            self.scale_data = False
            compression = False
            print('All results produced are for whitened data')
        
        # Centring and scaling
        if self.scale_data:
            if self.center=='mean':
                scale = 'std'
            elif self.center=='median':
                scale = 'mad' 
        else:
            scale = 'None'
            warnings.warn('Without scaling, convergence to optima is not given')
            
         # Data Compression for flat tables if required                
        if (p>n) and compression:
            V,S,U = np.linalg.svd(X.T,full_matrices=False)
            X = U.T*np.diag(S)
            n,p = X.shape
            dimensions = 1
        else:
            dimensions = 0            
        
        # Initiate centring object and scale X data 
        centring = robcent(center=self.center,scale=scale)      
  
      if self.center_data:
            Xs = centring.fit(X,trimming=trimming)
            mX = centring.col_loc_
            sX = centring.col_sca_
        else:
            Xs = X
            mX = np.zeros((1,p))
            sX = np.ones((1,p))

        fit_arguments = {}
            
        # Data whitening (best practice for ICA)
        if self.whiten_data:
            V,S,U = np.linalg.svd(Xs.T,full_matrices=False)
            del U
            K = (V/S)[:,:p]
            del V,S
            Xs = np.matmul(Xs, K)
            Xs *= np.sqrt(p)

        # Pre-process y data when available 
        if flag != 'one-block':
            
            ny = y.shape[0]
            if len(y.shape) < 2:
                y = np.matrix(y).reshape((ny,1))
#            py = y.shape[1]
            if ny != n:
                raise(MyException('X and y number of rows must agree'))
            if self.copy:
                y0 = copy.deepcopy(y)
                self.y0 = y0
                
            if self.center_data:
                ys = centring.fit(y,trimming=trimming)
                my = centring.col_loc_
                sy = centring.col_sca_ 
            else:
                ys = y
                my = 0
                sy = 1
            ys = ys.astype('float64')
        
        else:
            ys = None
                

        # Initializing output matrices
        W = np.zeros((p,h))
        T = np.zeros((n,h))
        P = np.zeros((p,h))
        B = np.zeros((p,h))
        R = np.zeros((p,h))
        B_scaled = np.zeros((p,h))
        C = np.zeros((h,1))
        Xev = np.zeros((h,1))
        assovec = np.zeros((h,1))
        Maxobjf = np.zeros((h,1))

        # Initialize deflation matrices 
        E = copy.deepcopy(Xs)
        f = ys

        bi = np.zeros((p,1))
            
        # Define grid optimization ranges 
        optrange = np.sign(self.optrange)
        optmax = self.optrange[1]
        stop0s = np.arcsin(optrange[0])
        stop1s = np.arcsin(optrange[1])
        stop1c = np.arccos(optrange[0])
        stop0c = np.arccos(optrange[1])
        anglestart = max(stop0c,stop0s)
        anglestop = max(stop1c,stop1s)
        nangle = np.linspace(anglestart,anglestop,ndir,endpoint=False)            
        alphamat = np.matrix([np.cos(nangle), np.sin(nangle)])
        if optmax != 1:
            alphamat *= optmax
        setattr(self,'_stop0c',stop0c)
        setattr(self,'_stop0s',stop0s)
        setattr(self,'_stop1c',stop1c)
        setattr(self,'_stop1s',stop1s)
        setattr(self,'optmax',optmax)
        
        if p>2:
            anglestart = min(self._stop0c,self._stop0s)
            anglestop = min(self._stop1c,self._stop1s)
            nangle = np.linspace(anglestart,anglestop,ndir,endpoint=True)
            alphamat2 = np.matrix([np.cos(nangle), np.sin(nangle)])
            if self.optmax != 1:
                alphamat2 *= self.optmax
                
        # Arguments for grid plane
        grid_args = { 
                     'alpha': self.alpha,
                     'alphamat': alphamat,
                     'ndir': ndir,
                     'trimming': self.trimming,
                     'biascorr': biascorr, 
                     'dmetric' : 'euclidean'
                     }
        if flag=='two-block':
            grid_args['y'] = f
            
         # Arguments for grid plane #2
        grid_args_2 = { 
                     'alpha': self.alpha,
                     'alphamat': alphamat2,
                     'ndir': ndir,
                     'trimming': self.trimming,
                     'biascorr': biascorr, 
                     'dmetric' : 'euclidean'
                     }
        if flag=='two-block':
            grid_args_2['y'] = f
            

        # Itertive coefficient estimation
        for i in range(0,h):

            if p==2:
                wi,maximo = self._gridplane(E,
                                            pi_arguments=fit_arguments,
                                            **grid_args
                                            )
           
            elif p>2:
                
                afin = np.zeros((p,1)) # final parameters for linear combinations
                Z = copy.deepcopy(E)
                # sort variables according to criterion
                meas = [self.most.fit(E[:,k],
                            **grid_args) 
                            for k in np.arange(0,p)]
                if self.square_pi:
                    meas = np.square(meas)
                wi,maximo = self._gridplane(Z[:,0:2],**grid_args)
                Zopt = Z[:,0:2]*wi 
                afin[0:2]=wi
                for j in np.arange(2,p):
                    projmat = np.matrix([np.array(Zopt[:,0]).reshape(-1),
                                         np.array(Z[:,j]).reshape(-1)]).T
                    wi,maximo = self._gridplane(projmat,
                                                **grid_args
                                                )
                    Zopt = Zopt*float(wi[0]) + Z[:,j]*float(wi[1])
                    afin[0:(j+1)] = afin[0:(j+1)]*float(wi[0])
                    afin[j] = float(wi[1])

                tj = Z*afin
                objf = self.most.fit(tj,
                                     **{**fit_arguments,**grid_args}
                                    )
                if self.square_pi:
                    objf *= objf
    

                # outer loop to run until convergence
                objfold = copy.deepcopy(objf)
                objf = -1000
                afinbest = afin
                ii = 0
                maxiter_2j = 2**round(np.log2(maxiter)) 
                
                while ((ii < maxiter+1) and (abs(objfold - objf)/abs(objf) > 1e-4)):
                    for j in np.arange(0,p):
                        projmat = np.matrix([np.array(Zopt[:,0]).reshape(-1),
                                         np.array(Z[:,j]).reshape(-1)]).T
                        if j > 16:
                            divv = maxiter_2j
                        else:
                            divv = min(2**j,maxiter_2j)
                        
                        wi,maximo = self._gridplane_2(projmat,
                                                      q=afin[j],
                                                      div=divv,
                                                      **grid_args_2
                                                      )
                        Zopt = Zopt*float(wi[0,0]) + Z[:,j]*float(wi[1,0])
                        afin *= float(wi[0,0])
                        afin[j] += float(wi[1,0])
                        
                    # % evaluate the objective function:
                    tj = Z*afin
                    
                    objfold = copy.deepcopy(objf)
                    objf = self.most.fit(tj,
                                         q=afin,
                                         **grid_args
                                         )
                    if self.square_pi:
                        objf *= objf
                    
                    if  objf!=objfold:
                        if self.constraint == 'norm':
                            afinbest = afin/np.sqrt(np.sum(np.square(afin)))
                        else:
                            afinbest = afin
                            
                    ii +=1
                    if self.verbose:
                        print(str(ii))
                #endwhile
                
                afinbest = afin
                wi = np.zeros((p,1))
                wi = afinbest
                Maxobjf[i] = objf
            # endif;%if p>2;

            # Computing projection weights and scores
            ti = E*wi
            nti = np.linalg.norm(ti)
            pi = E.T*ti / (nti**2)
            if self.whiten_data:
                wi /= np.sqrt((wi**2).sum())
                wi = K*wi
            wi0 = wi
            wi = np.array(wi)
            if len(W[:,i].shape) == 1:
                wi = wi.reshape(-1)
            W[:,i] = wi
            T[:,i] = np.array(ti).reshape(-1)
            P[:,i] = np.array(pi).reshape(-1)
            
            if flag != 'one-block':
                criteval = self.most.fit(E*wi0,
                                         **grid_args
                                         )
                if self.square_pi:
                    criteval *= criteval
                    
                assovec[i] = criteval
                

            # Deflation of the datamatrix guaranteeing orthogonality restrictions
            E -= ti*pi.T
 
            # Calculate R-Weights
            R = np.dot(W[:,0:(i+1)],pinv2(np.dot(P[:,0:(i+1)].T,W[:,0:(i+1)]),check_finite=False))
        
            # Execute regression y~T if y is present. Generate regression estimates.
            if flag != 'one-block':
                if regopt=='OLS':
                    ci = np.dot(ti.T,ys)/(nti**2)
                elif regopt == 'robust':
                    linfit = rm(fun=fun,probp1=probp1,probp2=probp2,probp3=probp3,
                                centre=self.center,scale=scale,
                                start_cutoff_mode='specific',verbose=self.verbose)
                    linfit.fit(ti,ys)
                    ci = linfit.coef_
                elif regopt == 'quantile':
                    linfit = QuantReg(y,ti)
                    model = linfit.fit(q=quantile)
                    ci = model.params
                # end regression if
                
                C[i] = ci
                bi = np.dot(R,C[0:(i+1)])
                bi_scaled = bi
                bi = np.multiply(np.reshape(sy/sX,(p,1)),bi)
                B[:,i] = bi[:,0]
                B_scaled[:,i] = bi_scaled[:,0]

        # endfor; Loop for latent dimensions

        # Re-adjust estimates to original dimensions if data have been compressed 
        if dimensions:
            B = V[:,0:p]*B
            B_scaled = V[:,0:p]*B_scaled
            R = V[:,0:p]*R
            W = V[:,0:p]*W
            P = V[:,0:p]*P
            bi = B[:,h-1]
            if self.center_data:
                Xs = centring.fit(X0,trimming=trimming)
                mX = centring.col_loc_
                sX = centring.col_sca_
            else:
                Xs = X0
                mX = np.zeros((1,p))
                sX = np.ones((1,p))
        
        bi = bi.astype("float64")
        if flag != 'one-block':            
            # Calculate scaled and unscaled intercepts
            if(self.center == "mean"):
                intercept = sps.trim_mean(y - np.matmul(X0,bi),trimming)
            else:
                intercept = np.median(np.reshape(y - np.matmul(X0,bi),(-1)))
            yfit = np.matmul(X0,bi) + intercept
            if not(scale == 'None'):
                if (self.center == "mean"):
                    b0 = np.mean(ys - np.matmul(Xs.astype("float64"),bi))
                else:
                    b0 = np.median(np.array(ys.astype("float64") - np.matmul(Xs.astype("float64"),bi)))
            else:
                b0 = intercept
            
            # Calculate fit values and residuals 
            yfit = yfit    
            r = y - yfit
            setattr(self,"coef_",B)
            setattr(self,"intercept_",intercept)
            setattr(self,"coef_scaled_",B_scaled)
            setattr(self,"intercept_scaled_",b0)
            setattr(self,"residuals_",r)
            setattr(self,"fitted_",yfit)
            setattr(self,"y_loadings_",C)
            setattr(self,"y_loc_",my)
            setattr(self,"y_sca_",sy)
                
        setattr(self,"x_weights_",W)
        setattr(self,"x_loadings_",P)
        setattr(self,"x_rotations_",R)
        setattr(self,"x_scores_",T)
        setattr(self,"x_ev_",Xev)
        setattr(self,"crit_values_",assovec)
        setattr(self,"Maxobjf_",Maxobjf)
        
        if self.whiten_data:
            setattr(self,"whitening_",K)

        
        if mixing:
            setattr(self,"mixing_",np.linalg.pinv(W))
        
        
        setattr(self,"x_loc_",mX)
        setattr(self,"x_sca_",sX)

        setattr(self,'scaling',scale)
        if self.return_scaling_object:
            setattr(self,'scaling_object_',centring)
        
        return(T)   


    def predict(self,Xn):
        (n,p) = Xn.shape
        if p!= self.coef_.shape[0]:
            raise(ValueError('New data must have seame number of columns as the ones the model has been trained with'))
        return(np.matmul(Xn,self.coef_) + self.intercept_)
        
    def transform(self,Xn):
        (n,p) = Xn.shape
        if p!= self.coef_.shape[0]:
            raise(ValueError('New data must have seame number of columns as the ones the model has been trained with'))
        Xnc = self.scaling_object_.scale_data(Xn,self.x_loc_,self.x_sca_)
        return(Xnc*self.x_rotations_)