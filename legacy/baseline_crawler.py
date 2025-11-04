# baseline_crawler.py — raccoglie HTTPS "normale"
from playwright.sync_api import sync_playwright
import time, json, random
SITES=["https://www.wikipedia.org","https://www.mozilla.org","https://www.bbc.com","https://www.reddit.com"]
def run(minutes=60, out="baseline.jsonl"):
    with sync_playwright() as p, open(out,"w") as f:
        b=p.chromium.launch(headless=True); c=b.new_context(); pg=c.new_page()
        t0=time.time(); last=time.time()
        while time.time()-t0<minutes*60:
            u=random.choice(SITES); st=time.time(); pg.goto(u, wait_until="domcontentloaded")
            dt=time.time()-st; f.write(json.dumps({"t":int(time.time()),"u":u,"dt":dt})+"\n"); f.flush()
            time.sleep(0.5)
if __name__=="__main__": run(60)