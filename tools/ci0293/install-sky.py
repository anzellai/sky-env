#!/usr/bin/env python3
"""Official0293 install to an exclusive CI tool directory; no release fallback."""
import argparse,gzip,hashlib,json,re,subprocess,struct,tarfile,urllib.request
from pathlib import Path

def need(x,s):
 if not x:raise ValueError(s)
class Bound:
 def __init__(self,r,limit):self.r=r;self.left=limit
 def read(self,n=-1):
  n=self.left+1 if n<0 else min(n,self.left+1);b=self.r.read(n);need(len(b)<=self.left,'ExpandedArchiveBound');self.left-=len(b);return b

def main():
 p=argparse.ArgumentParser();p.add_argument('--archive-sha',default='');p.add_argument('--binary-sha',default='');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 need(all(not v or re.fullmatch('[0-9a-f]{64}',v) for v in [a.archive_sha,a.binary_sha]),'InvalidOptionalSHA');need(not a.out.exists(),'ToolOutputExists');a.out.mkdir(parents=True,mode=0o700)
 base='https://github.com/anzellai/sky/releases/download/v0.29.3/';name='sky-darwin-arm64.tar.gz'
 sums=urllib.request.urlopen(base+'checksums.txt',timeout=60).read(1024*1024).decode();rows=[l.split() for l in sums.splitlines() if l.split() and l.split()[-1]==name];need(len(rows)==1 and len(rows[0])==2 and re.fullmatch('[0-9a-f]{64}',rows[0][0]),'OfficialChecksumMissing');need(not a.archive_sha or rows[0][0]==a.archive_sha,'OfficialChecksumMismatch');a.archive_sha=rows[0][0]
 archive=a.out/name;h=hashlib.sha256();n=0
 with urllib.request.urlopen(base+name,timeout=180) as r,archive.open('xb') as w:
  archive.chmod(0o600)
  while True:
   b=r.read(65536)
   if not b:break
   n+=len(b);need(n<=256*1024*1024,'ArchiveBound');h.update(b);w.write(b)
 need(h.hexdigest()==a.archive_sha,'DownloadedArchiveMismatch');seen=set()
 with archive.open('rb') as compressed,gzip.GzipFile(fileobj=compressed) as g:
  with tarfile.open(fileobj=Bound(g,1025*1024*1024),mode='r|') as t:
   for m in t:
    need(m.name in ['sky-darwin-arm64','sky-ffi-inspect-sky-darwin-arm64'] and m.name not in seen and m.type in (tarfile.REGTYPE,tarfile.AREGTYPE) and not m.pax_headers and not t.pax_headers and 32<=m.size<=512*1024*1024,'UnsafeReleaseMember');seen.add(m.name)
    out=a.out/('sky' if m.name=='sky-darwin-arm64' else 'sky-ffi-inspect');r=t.extractfile(m);need(r is not None,'MissingReleaseData')
    with out.open('xb') as w:
     while True:
      b=r.read(65536)
      if not b:break
      w.write(b)
    out.chmod(0o755)
   while True:
    b=t.fileobj.read(65536)
    if not b:break
    need(not any(b),'UnexpectedArchiveTail')
 need(len(seen)==2,'MissingReleaseMember');binary=a.out/'sky';actual_binary_sha=hashlib.sha256(binary.read_bytes()).hexdigest();need(not a.binary_sha or actual_binary_sha==a.binary_sha,'OfficialBinaryMismatch');a.binary_sha=actual_binary_sha
 header=struct.unpack('<8I',binary.read_bytes()[:32]);need(header[0]==0xfeedfacf and header[1]==0x0100000c and header[3]==2,'NotNativeARM64Compiler')
 r=subprocess.run([str(binary),'--version'],capture_output=True,check=True);need(r.stdout==b'sky v0.29.3\n' and not r.stderr,'NotOfficial0293')
 (a.out/'official-compiler.json').write_text(json.dumps({'officialRelease':True,'version':'0.29.3','archiveSHA256':a.archive_sha,'binarySHA256':a.binary_sha})+'\n');print('official compiler checksum and version verified')
if __name__=='__main__':main()
