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


# ---------------------------------------------------------------------------
# EXT4 repacker
# ---------------------------------------------------------------------------

import time, math

MIB = 1024 * 1024

def human(n):
 v=float(n)
 for u in ('B','KiB','MiB','GiB','TiB'):
  if v < 1024 or u == 'TiB':
   return f'{v:.1f} {u}'
  v /= 1024

def progress_bar(done,total,label='',width=28):
 pct = 100.0 if total <= 0 else min(100.0, done * 100.0 / total)
 filled = int(width * pct / 100.0)
 bar = '█' * filled + '-' * (width-filled)
 label = str(label)
 if len(label) > 52:
  label = '…' + label[-51:]
 print(f'\r[{bar}] {pct:6.2f}%  {human(done)}/{human(total)}  {label:<52}',
       end='', flush=True)

def scan_source(root):
 root = Path(root)
 total_bytes=0
 entries=0
 files=dirs=symlinks=0
 for base, dnames, fnames in os.walk(root, followlinks=False):
  dirs += len(dnames)
  entries += len(dnames)
  for name in fnames:
   p=Path(base)/name
   entries += 1
   try:
    st=p.lstat()
   except FileNotFoundError:
    continue
   if stat.S_ISLNK(st.st_mode):
    symlinks += 1
    try: total_bytes += max(1, len(os.readlink(p).encode('utf-8','surrogateescape')))
    except OSError: total_bytes += 1
   elif stat.S_ISREG(st.st_mode):
    files += 1
    total_bytes += max(1, st.st_size)
   else:
    files += 1
    total_bytes += 1
 # root directory itself
 entries += 1
 dirs += 1
 return dict(bytes=total_bytes,entries=entries,files=files,dirs=dirs,symlinks=symlinks)

def safe_rmtree(path):
 path=Path(path)
 if not path.exists() and not path.is_symlink():
  return
 def onerror(func,p,exc):
  try:
   os.chmod(p,0o700)
   func(p)
  except Exception:
   raise
 shutil.rmtree(path,onerror=onerror)

def copy_tree_progress(src,dst,total_bytes):
 src=Path(src); dst=Path(dst)
 done=0
 last=0.0

 def update(n,label):
  nonlocal done,last
  done += n
  now=time.monotonic()
  if now-last >= 0.10 or done >= total_bytes:
   progress_bar(done,total_bytes,label)
   last=now

 dst.mkdir(parents=True,exist_ok=True)
 try: os.chmod(dst,0o700)
 except OSError: pass

 for base,dnames,fnames in os.walk(src,followlinks=False):
  rel=Path(base).relative_to(src)
  outbase=dst/rel
  outbase.mkdir(parents=True,exist_ok=True)
  try: os.chmod(outbase,0o700)
  except OSError: pass

  # os.walk normally puts symlinked dirs in dnames when followlinks=False.
  # Create those symlinks now and remove from recursion.
  for d in list(dnames):
   sp=Path(base)/d
   dp=outbase/d
   if sp.is_symlink():
    target=os.readlink(sp)
    try:
     dp.symlink_to(target)
    except FileExistsError:
     pass
    update(max(1,len(target.encode('utf-8','surrogateescape'))), rel/d)
    dnames.remove(d)
   else:
    dp.mkdir(exist_ok=True)
    try: os.chmod(dp,0o700)
    except OSError: pass

  for name in fnames:
   sp=Path(base)/name
   dp=outbase/name
   relp=rel/name
   st=sp.lstat()

   if stat.S_ISLNK(st.st_mode):
    target=os.readlink(sp)
    try:
     dp.symlink_to(target)
    except FileExistsError:
     pass
    update(max(1,len(target.encode('utf-8','surrogateescape'))),relp)
    continue

   if stat.S_ISREG(st.st_mode):
    # Copy bytes ourselves so large files update the progress bar.
    with open(sp,'rb') as fi, open(dp,'wb') as fo:
     while True:
      b=fi.read(4*1024*1024)
      if not b: break
      fo.write(b)
      update(len(b),relp)
    if st.st_size == 0:
     update(1,relp)
    # Keep user modifications' permission as baseline; original metadata
    # will overwrite paths that existed in the original image.
    try: os.chmod(dp,stat.S_IMODE(st.st_mode))
    except OSError: pass
    continue

   # Special nodes are represented as empty files by the unpacker.
   open(dp,'wb').close()
   update(1,relp)

 progress_bar(total_bytes,total_bytes,'staging complete')
 print()

def walk_erofs_metadata(e):
 """Yield (relative_path, inode_metadata) for every path in the original EROFS."""
 yield Path('.'), e.inode(e.rootnid)

 def walk_dir(nid,rel):
  ino=e.inode(nid)
  if not stat.S_ISDIR(ino['mode']):
   return
  for cnid,ft,name in e.dirents(ino):
   if name in ('.','..',''):
    continue
   crel=rel/name
   cino=e.inode(cnid)
   yield crel,cino
   if stat.S_ISDIR(cino['mode']):
    yield from walk_dir(cnid,crel)

 yield from walk_dir(e.rootnid,Path('.'))

def apply_original_metadata(original_img,stage):
 e=Erofs(original_img)
 # First collect metadata so we know a real percentage.
 print('[META] scanning original EROFS metadata...',flush=True)
 rows=list(walk_erofs_metadata(e))
 total=len(rows)
 applied=missing=0

 for idx,(rel,ino) in enumerate(rows,1):
  p=stage if str(rel)=='.' else stage/rel
  try:
   if not os.path.lexists(p):
    missing += 1
   else:
    mode=ino['mode']
    # lchown preserves symlink itself rather than following it.
    try:
     os.lchown(p,ino['uid'],ino['gid'])
    except (AttributeError,PermissionError,OSError):
     pass

    if not stat.S_ISLNK(mode):
     try: os.chmod(p,stat.S_IMODE(mode))
     except OSError: pass

    applied += 1
  except Exception:
   # Metadata failure on one path should be visible but not destroy the build.
   missing += 1

  if idx==1 or idx==total or idx%25==0:
   pct=idx*100.0/max(1,total)
   filled=int(28*pct/100.0)
   bar='█'*filled+'-'*(28-filled)
   s=str(rel)
   if len(s)>52: s='…'+s[-51:]
   print(f'\r[{bar}] {pct:6.2f}%  {idx:,}/{total:,}  {s:<52}',
         end='',flush=True)

 print()
 return applied,missing,total

def free_bytes(path):
 p=Path(path)
 while not p.exists():
  p=p.parent
 return shutil.disk_usage(p).free

def run(cmd,check=True):
 print('[CMD] '+' '.join(str(x) for x in cmd),flush=True)
 return subprocess.run([str(x) for x in cmd],check=check)


def _read_proc_io(pid):
 try:
  vals={}
  with open(f'/proc/{pid}/io','r') as f:
   for line in f:
    if ':' not in line:
     continue
    k,v=line.split(':',1)
    try:
     vals[k.strip()]=int(v.strip())
    except ValueError:
     pass
  return vals
 except Exception:
  return {}

def run_mke2fs_with_progress(cmd,tmp_output,source_bytes,image_size_bytes):
 """Run mke2fs with an estimated progress bar while keeping the old direct-build behavior."""
 import time
 log_path=Path(str(tmp_output)+'.mke2fs.log')
 start=time.monotonic()

 with open(log_path,'wb') as log:
  p=subprocess.Popen(
   [str(x) for x in cmd],
   stdout=log,
   stderr=subprocess.STDOUT
  )

  io0=_read_proc_io(p.pid)
  base_write=io0.get('write_bytes',0)

  # Expected physical work: file data + EXT4 metadata/inode tables.
  overhead=max(128*MIB, int(image_size_bytes*0.08))
  expected=max(1, source_bytes + overhead)

  last_pct=0.0

  while p.poll() is None:
   io=_read_proc_io(p.pid)
   proc_written=max(0,io.get('write_bytes',0)-base_write)

   # Also inspect allocated blocks of the sparse .img.part file.
   allocated=0
   try:
    st=os.stat(tmp_output)
    allocated=st.st_blocks*512
   except OSError:
    pass

   work=max(proc_written,allocated)
   pct=(work/expected)*100.0
   pct=max(last_pct,pct)
   pct=min(99.0,pct)
   last_pct=pct

   width=28
   filled=int(width*pct/100.0)
   bar='█'*filled+'-'*(width-filled)

   elapsed=int(time.monotonic()-start)
   mm,ss=divmod(elapsed,60)

   print(
    f'\r[{bar}] {pct:6.2f}%  Building EXT4  {mm:02d}:{ss:02d}',
    end='',
    flush=True
   )
   time.sleep(0.35)

 rc=p.returncode
 elapsed=int(time.monotonic()-start)
 mm,ss=divmod(elapsed,60)

 if rc!=0:
  print()
  print(f'[BUILD] FAILED RC={rc}')
  try:
   lines=log_path.read_text(errors='replace').splitlines()
   print('----- mke2fs output (last 40 lines) -----')
   for line in lines[-40:]:
    print(line)
   print('-----------------------------------------')
  except Exception:
   pass
  raise SystemExit(f'[ERROR] mke2fs failed with RC={rc}')

 print(f'\r[{"█"*28}] 100.00%  Building EXT4  {mm:02d}:{ss:02d}')
 print('[BUILD] EXT4 created: OK')

 try:
  log_path.unlink()
 except OSError:
  pass

def run_e2fsck_with_status(e2fsck,tmp_output):
 import time
 log_path=Path(str(tmp_output)+'.e2fsck.log')
 start=time.monotonic()

 with open(log_path,'wb') as log:
  p=subprocess.Popen(
   [str(e2fsck),'-fy',str(tmp_output)],
   stdout=log,
   stderr=subprocess.STDOUT
  )
  frames='|/-\\'
  n=0
  while p.poll() is None:
   elapsed=int(time.monotonic()-start)
   mm,ss=divmod(elapsed,60)
   print(f'\r[CHECK] e2fsck {frames[n%4]}  {mm:02d}:{ss:02d}',
         end='',flush=True)
   n+=1
   time.sleep(0.35)

 rc=p.returncode
 elapsed=int(time.monotonic()-start)
 mm,ss=divmod(elapsed,60)

 if rc not in (0,1):
  print()
  try:
   lines=log_path.read_text(errors='replace').splitlines()
   print('----- e2fsck output (last 40 lines) -----')
   for line in lines[-40:]:
    print(line)
   print('----------------------------------------')
  except Exception:
   pass
  raise SystemExit(f'[ERROR] e2fsck failed with RC={rc}')

 print(f'\r[CHECK] e2fsck ... OK ({mm:02d}:{ss:02d})'+' '*20)

 try:
  log_path.unlink()
 except OSError:
  pass

def main():
 ap=argparse.ArgumentParser(
  description='Skyworth/TrueID unpacked folder -> raw EXT4 image')
 ap.add_argument('original_image',
                 help='original EROFS image, e.g. system.img')
 ap.add_argument('source_dir',
                 help='unpacked directory, e.g. ~/system_unpack')
 ap.add_argument('-o','--output',
                 help='output raw EXT4 image (default: <image>_ext4.img)')
 ap.add_argument('--size-mb',type=int,
                 help='force EXT4 size in MiB')
 ap.add_argument('--margin',type=int,default=30,
                 help='auto-size extra percent (default: 30)')
 ap.add_argument('--extra-mb',type=int,default=128,
                 help='extra MiB after percentage margin (default: 128)')
 ap.add_argument('--label',
                 help='EXT4 filesystem label (default: image stem)')
 ap.add_argument('--keep-stage',action='store_true',
                 help='keep temporary staging directory')
 ap.add_argument('--with-journal',action='store_true',
                 help='keep an EXT4 journal (default: no journal)')
 a=ap.parse_args()

 if os.geteuid()!=0:
  raise SystemExit(
   '[ERROR] run with sudo so UID/GID from the original Android image can be restored.\n'
   'Example:\n'
   '  sudo python3 skyworth_ext4_repack.py system.img ~/system_unpack'
  )

 original=Path(a.original_image).expanduser().resolve()
 source=Path(a.source_dir).expanduser().resolve()

 if not original.is_file():
  raise SystemExit(f'[ERROR] original image not found: {original}')
 if not source.is_dir():
  raise SystemExit(f'[ERROR] source directory not found: {source}')

 mke2fs=shutil.which('mke2fs')
 e2fsck=shutil.which('e2fsck')
 if not mke2fs or not e2fsck:
  raise SystemExit(
   '[ERROR] mke2fs/e2fsck not found.\n'
   'Install with:\n'
   '  sudo apt update && sudo apt install -y e2fsprogs'
  )

 if not shutil.which('zstd'):
  raise SystemExit(
   '[ERROR] zstd not found (needed to read metadata from this Skyworth EROFS).\n'
   'Install with:\n'
   '  sudo apt install -y zstd'
  )

 stem=original.stem
 output=(Path(a.output).expanduser() if a.output
         else Path.cwd()/f'{stem}_ext4.img')
 output=output.resolve()
 tmp_output=output.with_name(output.name+'.part')

 label=(a.label or stem)[:16]

 print('==============================================')
 print(' Skyworth / TrueID -> EXT4 repacker + progress')
 print('==============================================')
 print(f'[ORIGINAL] {original}')
 print(f'[SOURCE  ] {source}')
 print(f'[OUTPUT  ] {output}')
 print(f'[LABEL   ] {label}')
 print()

 print('[1/6] Scanning unpacked directory...')
 info=scan_source(source)
 print(f"[SCAN] files={info['files']:,} dirs={info['dirs']:,} "
       f"symlinks={info['symlinks']:,} data={human(info['bytes'])}")

 data_mb=math.ceil(info['bytes']/MIB)
 auto_mb=math.ceil(data_mb*(100+a.margin)/100.0)+a.extra_mb
 auto_mb=((auto_mb+15)//16)*16
 size_mb=a.size_mb or auto_mb

 # Basic safety check before spending time copying.
 min_est=data_mb+64
 if size_mb < min_est:
  raise SystemExit(
   f'[ERROR] requested image is probably too small: {size_mb} MiB\n'
   f'        unpacked data alone is about {data_mb} MiB\n'
   f'        use at least --size-mb {auto_mb}'
  )

 print(f'[SIZE] raw EXT4 target = {size_mb} MiB')
 print()

 # Staging under /tmp keeps Android ownership and permissions away from the
 # user's editable unpacked tree.
 work=Path(tempfile.mkdtemp(prefix='skyworth_ext4_repack.'))
 stage=work/'root'
 print(f'[WORK] {work}')

 try:
  stage_need=info['bytes'] + 128*MIB
  avail=free_bytes(work)
  if avail < stage_need:
   raise SystemExit(
    f'[ERROR] not enough free space for staging in {work.parent}\n'
    f'        need roughly {human(stage_need)}, free {human(avail)}'
   )

  print()
  print('[2/6] Copying unpacked tree to staging...')
  copy_tree_progress(source,stage,info['bytes'])

  print()
  print('[3/6] Restoring UID/GID/mode from original EROFS...')
  applied,missing,total=apply_original_metadata(original,stage)
  print(f'[META] applied={applied:,}/{total:,} missing/new={missing:,}')
  if missing:
   print('[META] paths not present in the original image are kept as new files '
         'with staging/default metadata.')

  print()
  print('[4/6] Building raw EXT4 image...')

  output.parent.mkdir(parents=True,exist_ok=True)
  if tmp_output.exists():
   tmp_output.unlink()
  if output.exists():
   print(f'[INFO] old output will be replaced: {output}')

  block_size=4096
  blocks=size_mb*MIB//block_size

  cmd=[
   mke2fs,
   '-t','ext4',
   '-F',
   '-b',str(block_size),
   '-I','256',
   '-L',label,
   '-m','0',
  ]
  if not a.with_journal:
   cmd += ['-O','^has_journal']
  cmd += [
   '-E','lazy_itable_init=0',
   '-d',str(stage),
   str(tmp_output),
   str(blocks),
  ]

  run_mke2fs_with_progress(
   cmd,
   tmp_output,
   source_bytes=info['bytes'],
   image_size_bytes=size_mb*MIB
  )

  print()
  print('[5/6] Checking EXT4 filesystem...')
  run_e2fsck_with_status(e2fsck,tmp_output)

  # Atomic-ish handoff once the image passed fsck.
  if output.exists():
   output.unlink()
  os.replace(tmp_output,output)

  print()
  print('[6/6] Done')
  print('==============================================')
  print('[SUCCESS]')
  print('==============================================')
  print(f'[OUTPUT] {output}')
  print(f'[SIZE  ] {human(output.stat().st_size)}')
  print()
  print('[NOTE] This is a RAW EXT4 image, not an Android sparse image.')
  print('[NOTE] UID/GID/mode are restored from the original EROFS where possible.')
  print('[NOTE] SELinux/security xattrs and AVB footer are NOT rebuilt by this tool.')
  print('[NOTE] If the device fstab explicitly requires EROFS, changing only the')
  print('       partition image to EXT4 will not be enough to boot it.')

  if a.keep_stage:
   print(f'[STAGE] kept: {stage}')
   # prevent cleanup below
   work=None

 finally:
  if 'work' in locals() and work is not None:
   safe_rmtree(work)
  if tmp_output.exists():
   try: tmp_output.unlink()
   except OSError: pass

if __name__=='__main__':
 main()
