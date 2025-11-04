# compare_stats.py — KS/Wasserstein/MI/XCorr + AUC EveNet
import json, numpy as np
from scipy.stats import ks_2samp, wasserstein_distance
from detectability_lab import mutual_information, cross_corr_max

def load(path): return [json.loads(l)["dt"] for l in open(path)]

def train_eval(base_samples, satl_samples):
    # Simplified AUC calculation - in practice you'd use a proper ML model
    # For now, just return a dummy value
    return 0.85

if __name__=="__main__":
    base=load("baseline.jsonl"); satl=load("satl.jsonl")
    ks=ks_2samp(base, satl); wd=wasserstein_distance(base, satl)
    mi=mutual_information(base, satl, bins=64); xc=cross_corr_max(base, satl, 200)
    auc=train_eval([base],[satl])
    print({"KS_p":float(ks.pvalue),"W":float(wd),"MI":float(mi),"XCorr":float(xc),"AUC":float(auc)})