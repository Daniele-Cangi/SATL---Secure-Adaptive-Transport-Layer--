# histogram_fitter.py
from bisect import bisect_left
def inv_cdf_sampler(bins, cdf, u):
    # bins: edge list monotona; cdf: cumulata in [0,1]
    i = bisect_left(cdf, u)
    i = min(max(i,1), len(bins)-1)
    a,b=bins[i-1],bins[i]
    return a + (b-a)*(u-cdf[i-1])/max(cdf[i]-cdf[i-1],1e-9)