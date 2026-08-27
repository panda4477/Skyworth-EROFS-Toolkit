#!/usr/bin/env python3
import argparse, os, stat, struct, subprocess, tempfile, shutil, sys
from pathlib import Path

def align(x,a): return (x+a-1)//a*a
class Erofs:
 def __init__(self,path):
  self.path=Path(path); self.f=open(path,'rb'); self.f.seek(1024); self.sb=self.f.read(144)
  if struct.unpack_from('<I',self.sb,0)[0]!=0xe0f5e1e2: raise ValueError('not EROFS')
  self.blkszbits=self.sb[12]; self.bs=1<<self.blkszbits; self.rootnid=struct.unpack_from('<H',self.sb,14)[0]
  self.meta=struct.unpack_from('<I',self.sb,40)[0]; self.feature_incompat=struct.unpack_from('<I',self.sb,80)[0]; self.avail=struct.unpack_from('<H',self.sb,84)[0]
  self.meta_off=self.meta*self.bs
 def rd(self,o,n): self.f.seek(o); return self.f.read(n)
 def inode(self,nid):
  off=self.meta_off+nid*32; b=self.rd(off,64); fmt,xic,mode,nb=struct.unpack_from('<HHHH',b,0); ver=fmt&1; dl=(fmt>>1)&7; isz=64 if ver else 32
  size=struct.unpack_from('<Q' if ver else '<I',b,8)[0]; iu=struct.unpack_from('<I',b,16)[0]
  if ver:
   uid,gid=struct.unpack_from('<II',b,24); mtime=struct.unpack_from('<Q',b,32)[0]
  else:
   uid,gid=struct.unpack_from('<HH',b,24); mtime=struct.unpack_from('<I',b,12)[0]
  xsz=0 if xic==0 else 12+4*(xic-1)
  return dict(nid=nid,off=off,fmt=fmt,xic=xic,xsz=xsz,mode=mode,ver=ver,dl=dl,isz=isz,size=size,iu=iu,uid=uid,gid=gid,mtime=mtime)
 def read_flat(self,ino):
  size=ino['size']; dl=ino['dl']; bs=self.bs; nblocks=(size+bs-1)//bs
  if dl==0:
   return self.rd(ino['iu']*bs,size)
  if dl!=2: raise ValueError('not flat')
  lastblk=max(0,nblocks-1); reglen=lastblk*bs; out=b''
  if reglen: out=self.rd(ino['iu']*bs,reglen)
  tail_len=size-reglen
  if tail_len:
   tail_off=ino['off']+ino['isz']+ino['xsz']+(reglen & (bs-1))
   out+=self.rd(tail_off,tail_len)
  return out[:size]
 def comp_info(self,ino):
  end=ino['off']+ino['isz']+ino['xsz']; mh_off=align(end,8); mh=self.rd(mh_off,8)
  advise=struct.unpack_from('<H',mh,4)[0]; alg=mh[6]; cb=mh[7]; lbits=self.blkszbits+(cb&0xf)
  return mh_off,advise,alg,lbits
 def decode_compact(self,ino,lcn):
  end=ino['off']+ino['isz']+ino['xsz']; mh_off,adv,alg,lbits=self.comp_info(ino); ebase=mh_off+8
  total=(ino['size']+(1<<lbits)-1)>>lbits; c4=((32-ebase%32)//4)&7; c2=0
  if adv&1 and c4<total: c2=((total-c4)//16)*16
  orig=lcn; pos=ebase; shift=2
  if lcn>=c4:
   pos+=c4*4; lcn-=c4
   if lcn<c2: shift=1
   else: pos+=c2*2; lcn-=c2
  pos+=lcn*(1<<shift); vcnt=2 if (1<<shift)==4 and lbits<=14 else 16 if (1<<shift)==2 and lbits<=12 else None
  if not vcnt: raise NotImplementedError('compact pack unsupported')
  packsz=vcnt<<shift; bytes_=pos&(packsz-1); base=pos-bytes_; blob=self.rd(base,packsz); i=bytes_>>shift
  lobits=max(lbits,12); encodebits=(packsz-4)*8//vcnt
  def dbits(idx):
   bit=encodebits*idx; bo=bit//8; sh=bit&7; raw=blob[bo:bo+8]; val=int.from_bytes(raw,'little')>>sh
   return val&((1<<lobits)-1),(val>>lobits)&3
  lo,typ=dbits(i); d={'lcn':orig,'type':typ,'lo':lo,'adv':adv,'alg':alg,'lbits':lbits}
  if typ==2:
   d['clusterofs']=1<<lbits
   if lo&0x800: d['compressedblks']=lo&~0x800; d['delta0']=1
   elif i+1!=vcnt: d['delta0']=lo
   else:
    lo2,t2=dbits(i-1); d['delta0']=(0 if t2!=2 else 1 if lo2&0x800 else lo2)+1
  else:
   d['clusterofs']=lo; big=bool(adv&2); nblk=0 if big else 1; ii=i
   if not big:
    while ii>0:
     ii-=1; l,t=dbits(ii)
     if t==2: ii-=l
     if ii>=0: nblk+=1
   else:
    while ii>0:
     ii-=1; l,t=dbits(ii)
     if t==2:
      if l&0x800: ii-=1; nblk+=l&~0x800; continue
      if l<=1: raise ValueError('bad d0')
      ii-=l-2; continue
     nblk+=1
   d['pblk']=struct.unpack_from('<I',blob,packsz-4)[0]+nblk
  return d
 def decode_full(self,ino,lcn):
  end=ino['off']+ino['isz']+ino['xsz']; mh_off,adv,alg,lbits=self.comp_info(ino); start=align(end,8)+8+8 # FULL_INDEX_START = MAP_HEADER_END(end)+8
  b=self.rd(start+lcn*8,8); ad,co=struct.unpack_from('<HH',b,0); typ=ad&3
  d={'lcn':lcn,'type':typ,'lo':co,'clusterofs':(1<<lbits if typ==2 else co),'adv':adv,'alg':alg,'lbits':lbits}
  if typ==2:
   d0,d1=struct.unpack_from('<HH',b,4)
   if d0&0x800: d['compressedblks']=d0&~0x800; d0=1
   d['delta0']=d0; d['delta1']=d1
  else: d['pblk']=struct.unpack_from('<I',b,4)[0]
  return d
 def zstd_decode(self,blob,expected):
  magic=b'\x28\xb5\x2f\xfd'; idx=blob.find(magic)
  if idx<0: raise ValueError('zstd magic not found')
  p=subprocess.run(['zstd','-q','-d','-c'],input=blob[idx:],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if p.returncode: raise ValueError('zstd: '+p.stderr.decode(errors='replace'))
  if len(p.stdout)<expected: raise ValueError(f'zstd short {len(p.stdout)} < {expected}')
  return p.stdout[:expected]
 def read_compressed(self,ino,progress=None):
  _,adv,alg,lbits=self.comp_info(ino); L=1<<lbits; total=(ino['size']+L-1)//L
  dec=self.decode_compact if ino['dl']==3 else self.decode_full
  rec=[dec(ino,i) for i in range(total)]
  heads=[]
  for r in rec:
   if r['type']!=2:
    ls=r['lcn']*L+r['clusterofs']; heads.append((ls,r))
  # synthesize physical counts from CBLKCNT/next pblk
  out=bytearray(ino['size'])
  for k,(ls,r) in enumerate(heads):
   if ls>=ino['size']: continue
   le=heads[k+1][0] if k+1<len(heads) else ino['size']; le=min(le,ino['size'])
   if le<=ls: continue
   need=le-ls
   # determine pblocks
   pblks=None
   # first nonhead after this head may contain CBLKCNT
   nxt_lcn=r['lcn']+1
   if nxt_lcn<len(rec) and rec[nxt_lcn]['type']==2 and rec[nxt_lcn].get('compressedblks'):
    pblks=rec[nxt_lcn]['compressedblks']
   if pblks is None and k+1<len(heads) and heads[k+1][1].get('pblk',0)>=r.get('pblk',0):
    diff=heads[k+1][1]['pblk']-r['pblk']; pblks=diff if diff>0 else 1
   if pblks is None: pblks=1
   phys=self.rd(r['pblk']*self.bs,pblks*self.bs)
   if r['type']==0:
    data=phys[:need]
   else:
    data=self.zstd_decode(phys,need)
   out[ls:le]=data[:need]
   if progress: progress(need)
  return bytes(out)
 def read_data(self,ino,progress=None):
  if ino['dl'] in (0,2):
   data=self.read_flat(ino)
   if progress: progress(len(data))
   return data
  if ino['dl'] in (1,3): return self.read_compressed(ino,progress)
  raise NotImplementedError(f'datalayout {ino["dl"]}')
 def dirents(self,ino):
  data=self.read_data(ino); bs=self.bs; out=[]
  pos=0
  while pos<len(data):
   chunk=data[pos:min(pos+bs,len(data))]
   if len(chunk)<12: break
   no=struct.unpack_from('<H',chunk,8)[0]
   if no==0 or no%12: raise ValueError(f'bad dir nameoff {no} nid {ino["nid"]} pos {pos}')
   cnt=no//12
   for i in range(cnt):
    nid,nameoff,ft,res=struct.unpack_from('<QHBB',chunk,i*12)
    nextoff=struct.unpack_from('<H',chunk,(i+1)*12+8)[0] if i+1<cnt else len(chunk)
    name=chunk[nameoff:nextoff].split(b'\0',1)[0].decode('utf-8','surrogateescape')
    out.append((nid,ft,name))
   pos+=len(chunk)
  return out
 def scan_tree(self):
  """Pre-scan tree for progress totals without extracting files."""
  total_bytes=0
  total_items=0
  counts={'files':0,'dirs':0,'symlinks':0}
  seen_dirs=set()

  print('[SCAN] reading filesystem tree...', flush=True)

  def walk(nid):
   nonlocal total_bytes,total_items
   ino=self.inode(nid); mode=ino['mode']
   total_items+=1

   if total_items==1 or total_items%100==0:
    print(f'\r[SCAN] entries found: {total_items:,}',end='',flush=True)

   if stat.S_ISDIR(mode):
    counts['dirs']+=1
    if nid in seen_dirs:
     return
    seen_dirs.add(nid)
    for cnid,ft,name in self.dirents(ino):
     if name in ('.','..',''): continue
     walk(cnid)

   elif stat.S_ISLNK(mode):
    counts['symlinks']+=1
    total_bytes+=max(1,ino['size'])

   elif stat.S_ISREG(mode):
    counts['files']+=1
    total_bytes+=max(1,ino['size'])

   else:
    counts['files']+=1
    total_bytes+=1

  walk(self.rootnid)
  print(f'\r[SCAN] entries found: {total_items:,} — done'+' '*20,flush=True)
  return total_bytes,total_items,counts

 def extract(self,outdir,symlink_mode='auto',show_progress=True):
  import json, errno, time
  outdir=Path(outdir); outdir.mkdir(parents=True,exist_ok=True)

  total_bytes,total_items,scan_counts=self.scan_tree()
  stats={'files':0,'dirs':0,'symlinks':0,'symlink_markers':0}
  symlink_map={}
  done_bytes=0
  done_items=0
  last_draw=0.0
  last_pct=-1.0
  current=''

  def human(n):
   units=('B','KiB','MiB','GiB','TiB')
   v=float(n)
   for u in units:
    if v<1024 or u==units[-1]:
     return f'{v:.1f} {u}'
    v/=1024

  print(f"[SCAN] files={scan_counts['files']:,} dirs={scan_counts['dirs']:,} "
        f"symlinks={scan_counts['symlinks']:,} logical-data={human(total_bytes)}",
        flush=True)

  def draw(force=False):
   nonlocal last_draw,last_pct
   if not show_progress:
    return
   now=time.monotonic()
   pct=100.0 if total_bytes<=0 else min(100.0,done_bytes*100.0/total_bytes)

   # redraw when % changes enough or at least every 0.15 sec
   if not force and (now-last_draw)<0.15 and abs(pct-last_pct)<0.10:
    return

   width=28
   filled=int(width*pct/100.0)
   bar='█'*filled+'-'*(width-filled)
   name=current
   if len(name)>58:
    name='…'+name[-57:]
   print(
    f'\r[{bar}] {pct:6.2f}%  '
    f'{human(done_bytes)}/{human(total_bytes)}  '
    f'{done_items:,}/{total_items:,}  {name:<58}',
    end='',
    flush=True
   )
   last_draw=now; last_pct=pct

  def advance(n=0,item=False,path=None):
   nonlocal done_bytes,done_items,current
   if path is not None:
    current=str(path)
   if n:
    done_bytes+=n
   if item:
    done_items+=1
   draw(False)

  def marker_for(path,target):
   marker=path.with_name(path.name+'.__symlink__')
   marker.parent.mkdir(parents=True,exist_ok=True)
   marker.write_text(target,encoding='utf-8',errors='surrogateescape')
   rel=str(path.relative_to(outdir))
   symlink_map[rel]=target
   stats['symlink_markers']+=1

  def make_symlink(path,target):
   path.parent.mkdir(parents=True,exist_ok=True)

   if symlink_mode=='skip':
    symlink_map[str(path.relative_to(outdir))]=target
    return

   if symlink_mode=='marker':
    marker_for(path,target)
    return

   try:
    path.symlink_to(target)
   except FileExistsError:
    pass
   except OSError as ex:
    fallback_errnos={errno.EPERM,errno.EACCES,errno.ENOTSUP,errno.EROFS,errno.EINVAL}
    if symlink_mode=='real' or ex.errno not in fallback_errnos:
     raise
    marker_for(path,target)

  def walk(nid,path):
   ino=self.inode(nid); mode=ino['mode']
   rel=path.relative_to(outdir) if path!=outdir else Path('.')
   advance(path=rel)

   if stat.S_ISDIR(mode):
    path.mkdir(parents=True,exist_ok=True)
    stats['dirs']+=1
    try: os.chmod(path,stat.S_IMODE(mode))
    except OSError: pass
    advance(item=True)

    for cnid,ft,name in self.dirents(ino):
     if name in ('.','..',''): continue
     walk(cnid,path/name)

   elif stat.S_ISLNK(mode):
    # symlinks are tiny; count their logical size after decoding
    data=self.read_data(ino)
    target=data.decode('utf-8','surrogateescape')
    make_symlink(path,target)
    stats['symlinks']+=1
    advance(max(1,len(data)),item=True)

   elif stat.S_ISREG(mode):
    path.parent.mkdir(parents=True,exist_ok=True)

    # Update within compressed extents, so very large files don't look frozen.
    file_advanced=0
    def chunk_progress(n):
     nonlocal file_advanced
     file_advanced+=n
     advance(n)

    data=self.read_data(ino,chunk_progress)
    path.write_bytes(data)

    # read_flat reports once; compressed reports per extent. Guard if any bytes
    # were not reported due to a special layout.
    if file_advanced < max(1,len(data)):
     advance(max(1,len(data))-file_advanced)

    stats['files']+=1
    try: os.chmod(path,stat.S_IMODE(mode))
    except OSError: pass
    advance(item=True)

   else:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(b'')
    stats['files']+=1
    advance(1,item=True)

  draw(True)
  walk(self.rootnid,outdir)

  # Clamp small accounting differences.
  done_bytes=max(done_bytes,total_bytes)
  done_items=max(done_items,total_items)
  current='done'
  draw(True)
  if show_progress:
   print()

  if symlink_map:
   meta=outdir/'.skyworth_symlinks.json'
   meta.write_text(json.dumps(symlink_map,ensure_ascii=False,indent=2),
                   encoding='utf-8')

  return stats


def main():
 ap=argparse.ArgumentParser(
  description='Easy Skyworth/TrueID EROFS unpacker with progress bar')
 ap.add_argument('image',help='EROFS .img file')
 ap.add_argument('-o','--output',help='output directory (optional)')
 ap.add_argument(
  '--symlink-mode',
  choices=['auto','real','marker','skip'],
  default='auto',
  help='default: auto')
 ap.add_argument('--no-progress',action='store_true',help='disable progress bar')
 a=ap.parse_args()

 image=Path(a.image)
 if not image.is_file():
  raise SystemExit(f'[ERROR] image not found: {image}')

 # Easy default: if launched from /mnt/<drive> under WSL, write to Linux home
 # so real symlinks work. Otherwise use current directory.
 if a.output:
  out=Path(a.output).expanduser()
 else:
  cwd=str(Path.cwd().resolve())
  if cwd.startswith('/mnt/'):
   out=Path.home()/(image.stem+'_unpack')
  else:
   out=Path.cwd()/(image.stem+'_unpack')

 if not shutil.which('zstd'):
  raise SystemExit('[ERROR] zstd not found; install with: sudo apt install -y zstd')

 print(f'[INPUT]  {image.resolve()}')
 print(f'[OUTPUT] {out.resolve()}')

 try:
  resolved=str(out.resolve())
 except Exception:
  resolved=str(out.absolute())

 if resolved.startswith('/mnt/'):
  print('[WARN] output is on a Windows drive through WSL.')
  print('[WARN] symlinks may become .__symlink__ marker files.')
  print(f'[TIP ] easiest full extraction: python3 {Path(__file__).name} {image.name}')

 e=Erofs(image)
 print(f'[INFO] rootnid={e.rootnid} block={e.bs} incompat={hex(e.feature_incompat)} '
       f'compr_bitmap={hex(e.avail)}',flush=True)

 stats=e.extract(out,a.symlink_mode,show_progress=not a.no_progress)

 print(f'[OK] extracted to: {out}')
 print(f"[OK] files={stats['files']} dirs={stats['dirs']} "
       f"symlinks={stats['symlinks']} markers={stats['symlink_markers']}")

 if stats['symlink_markers']:
  print(f'[INFO] symlink map: {out/".skyworth_symlinks.json"}')

if __name__=='__main__':
 main()
