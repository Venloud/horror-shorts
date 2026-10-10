"""Download a user-provided HTTPS MP4 without accepting private-network destinations."""
import argparse
import ipaddress
import socket
import urllib.parse
import urllib.request
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--url",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    u=urllib.parse.urlsplit(a.url)
    if u.scheme!="https" or not u.hostname or u.username or u.password:
        p.error("Expected a public HTTPS URL")
    for family,_,_,_,address in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
        ip=ipaddress.ip_address(address[0])
        if not ip.is_global: p.error("Private or reserved network destinations are not allowed")
    # Redirects are intentionally refused so validation applies to the actual destination.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):raise ValueError("Redirects are not supported; provide final MP4 URL")
    opener=urllib.request.build_opener(NoRedirect)
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    with opener.open(urllib.request.Request(a.url,headers={"User-Agent":"Mozilla/5.0"}),timeout=60) as response:
        with out.open("wb") as f:
            total=0
            while True:
                data=response.read(1024*1024)
                if not data:break
                total+=len(data)
                if total>250*1024*1024:raise RuntimeError("MP4 exceeds 250MB")
                f.write(data)
    print(f"Downloaded {total} bytes to {out}")
if __name__=="__main__":main()
