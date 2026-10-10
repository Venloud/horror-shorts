"""Download public HTTPS assets, validating each redirect and enforcing a size limit."""
import argparse
import ipaddress
import socket
import urllib.parse
from pathlib import Path
import requests

def validate(url):
    u=urllib.parse.urlsplit(url)
    if u.scheme!="https" or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise ValueError("Only public HTTPS URLs on port 443 are permitted")
    for _,_,_,_,addr in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(addr[0]).is_global:
            raise ValueError("Private or reserved address blocked")
    return url

def download(url,output,max_mb=900):
    out=Path(output)
    out.parent.mkdir(parents=True,exist_ok=True)
    session=requests.Session()
    session.trust_env=False
    for _ in range(8):
        validate(url)
        with session.get(url,stream=True,allow_redirects=False,timeout=(15,120),headers={"User-Agent":"clipper-assets/1.0"}) as r:
            if r.status_code in (301,302,303,307,308):
                location=r.headers.get("Location")
                if not location: raise RuntimeError("Redirect missing Location")
                url=urllib.parse.urljoin(url,location)
                continue
            r.raise_for_status()
            size=0
            try:
                with out.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        if not chunk:continue
                        size+=len(chunk)
                        if size>max_mb*1024*1024:raise RuntimeError("File exceeds size limit")
                        f.write(chunk)
            except BaseException:
                out.unlink(missing_ok=True)
                raise
            if size==0:raise RuntimeError("Empty download")
            print(f"Downloaded {size} bytes to {out}",flush=True)
            return out
    raise RuntimeError("Too many redirects")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--url",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--max-mb",type=int,default=900)
    a=p.parse_args()
    download(a.url,a.output,a.max_mb)

if __name__=="__main__":main()
