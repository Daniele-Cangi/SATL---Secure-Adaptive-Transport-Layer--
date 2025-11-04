# entropy_peer.py — micro servizio peer (si può replicare 3-5 volte)
from fastapi import FastAPI
import os
app=FastAPI()
@app.get("/entropy")
def entropy():
    return os.urandom(64)