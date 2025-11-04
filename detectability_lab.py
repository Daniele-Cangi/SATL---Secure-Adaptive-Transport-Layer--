# detectability_lab.py
import numpy as np
from sklearn.metrics import roc_auc_score

def auc_detect(scores_pos, scores_neg):
    y = np.array([1]*len(scores_pos)+[0]*len(scores_neg))
    s = np.array(scores_pos+scores_neg)
    return float(roc_auc_score(y,s))

def mutual_information(a, b, bins=64):
    a=np.asarray(a); b=np.asarray(b)
    H,_,_=np.histogram2d(a,b,bins=bins); P=H/ max(H.sum(),1)
    Pa=P.sum(axis=1,keepdims=True); Pb=P.sum(axis=0,keepdims=True)
    with np.errstate(divide='ignore', invalid='ignore'):
        Q=np.where((P>0)&(Pa>0)&(Pb>0), P*(np.log(P)-np.log(Pa)-np.log(Pb)), 0)
    return float(Q.sum())

def cross_corr_max(a,b,max_lag=200):
    a=np.asarray(a)-np.mean(a); b=np.asarray(b)-np.mean(b)
    ma=np.std(a)+1e-9; mb=np.std(b)+1e-9; best=0.0
    for k in range(-max_lag,max_lag+1):
        if k>=0: x=a[k:]; y=b[:len(x)]
        else:    x=a[:k]; y=b[-k:len(a)]
        if len(x)>8:
            c=abs(np.dot(x,y)/(len(x)*ma*mb)); best=max(best,float(c))
    return best