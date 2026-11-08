#!/usr/bin/env python3
"""Hosted synthetic compile/test only. Never run a user tool or assistant."""
import argparse,hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
from owned_process import Owner
from interruption import Interruption

def need(x,label):
 if not x:raise RuntimeError(label)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def blocked(p):return any(x=='.env' or x.startswith('.env.') or x=='env.local' for x in p.parts)
def source(root):
 rows={}
 for n in subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')[:-1]:
  q=Path(n)
  if blocked(q):continue
  f=root/q;need(f.is_file() and not f.is_symlink(),'SourceNotRegular');rows[n]=sha(f)
 return rows

def resolved_argv(argv, search_path):
 """The unchanged spawn gate uses execv: resolve ONLY the explicit child PATH."""
 need(bool(argv) and isinstance(argv[0], str), 'CommandArgumentsInvalid')
 program=argv[0]
 if not Path(program).is_absolute():
  need('/' not in program and '\\' not in program, 'RelativeCommandPathRefused')
  need(isinstance(search_path, str) and bool(search_path) and all(Path(p).is_absolute() for p in search_path.split(os.pathsep)), 'CommandSearchPathInvalid')
  program=shutil.which(program, path=search_path)
  need(program is not None, 'CommandExecutableMissing')
 program=Path(program).resolve(strict=True)
 need(program.is_absolute() and program.is_file() and os.access(program, os.X_OK), 'CommandExecutableInvalid')
 return [str(program), *argv[1:]]

def main():
 a=argparse.ArgumentParser();a.add_argument('app',choices=['sky-env','sky-log','jokeraces-bot']);a.add_argument('--head',required=True);a.add_argument('--tools',type=Path,required=True);x=a.parse_args();root=Path.cwd()
 need(re.fullmatch('[0-9a-f]{40}',x.head) is not None and subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==x.head,'WrongSource');need(subprocess.check_output(['uname','-m'],text=True).strip()=='arm64','ARM64Required')
 # GitHub checkout may materialize a tracked example; remove only dotenv files
 # BEFORE opening them, within this disposable CI checkout, never a user home.
 for n in subprocess.check_output(['git','ls-files','-z']).decode().split('\0')[:-1]:
  f=root/n
  if blocked(Path(n)) and (f.is_file() or f.is_symlink()):f.unlink()
 initial=source(root);out=root/'ci-results';out.mkdir(mode=0o700);scratch=root/'.ci-scratch';scratch.mkdir(mode=0o700);home=scratch/'home';home.mkdir();tool=x.tools.resolve();official=json.loads((tool/'official-compiler.json').read_text());need(official['officialRelease'] is True and official['version']=='0.29.5' and sha(tool/'sky')==official['binarySHA256'],'OfficialCompilerMismatch')
 ctx={'PATH':':'.join([str(tool),str(Path(shutil.which('go')).parent),'/opt/homebrew/bin','/usr/bin','/bin','/usr/sbin','/sbin']),'HOME':str(home),'TMPDIR':str(scratch),'LANG':'en_US.UTF-8','CI':'true','GOMAXPROCS':'3','GOFLAGS':'-p=1','GOCACHE':str(scratch/'go-cache'),'GOMODCACHE':str(scratch/'go-mod'),'ENV':'test','SKY_TEST_MODE':'1','SKY_DATA_DIR':str(scratch/'data'),'SKY_LIVE_STORE':'memory','JOKERACES_LITE_MEMORY':'1'}
 owner=Owner();interrupt=Interruption();interrupt.install();passed=cleanup=False;phases=[];guardlog=None
 def run(label,argv,timeout=1800):
  interrupt.raise_if_requested();f=out/(str(len(phases))+'-'+label+'.private.log')
  with f.open('xb') as w:
   f.chmod(0o600);p=owner.start(resolved_argv(argv,ctx['PATH']),root,ctx,w,expected_exit='command')
   try:p.communicate(timeout=timeout)
   except subprocess.TimeoutExpired:owner.stop(p);raise RuntimeError('PhaseDeadline') from None
   code=p.returncode;owner.stop(p)
  phases.append({'phase':label,'exit':code});need(code==0,'PhaseFailed')
 def copy(src,dst):
  need(src.exists(),'ArtifactMissing')
  if src.is_dir():
   need(all(not p.is_symlink() and (p.is_dir() or p.is_file()) and not blocked(p.relative_to(src)) for p in src.rglob('*')),'UnsafeArtifact');shutil.copytree(src,dst)
  else:need(src.is_file() and not src.is_symlink(),'UnsafeArtifact');dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
 try:
  guardlog=(out/'memory-guard.private.log').open('xb');Path(guardlog.name).chmod(0o600);guard=owner.start(['/bin/bash',str(root/'.ci-toolchain/scripts/mem-guard.sh')],root,ctx,guardlog,expected_exit=False);time.sleep(1);need(guard.poll() is None,'MemoryGuardNotRunning')
  run('install',['sky','install'])
  if x.app=='sky-env':run('check',['sky','check','src/Main.sky'])
  else:run('verify',['sky','verify'])
  if x.app=='jokeraces-bot':
   run('postgres-bundle',['sky','db','provision','--embed']);run('desktop-build',['sky','build','--embed','--target','desktop:mac','src/Main.sky'],2400)
  else:run('native-build',['sky','build','src/Main.sky'],2400)
  artifact=root/'ci-artifact';artifact.mkdir()
  if x.app=='jokeraces-bot':
   split=root/'.skyapp/desktop-mac/.split';copy(split/'backend/sky-out',artifact/'backend/sky-out');copy(split/'frontend/dist',artifact/'frontend/dist');copy(split/'frontend/sky-out/desktop',artifact/'frontend/sky-out/desktop');need(any(artifact.glob('frontend/dist/*.wasm')),'WasmMissing')
  else:copy(root/'sky-out'/('sky-env' if x.app=='sky-env' else 'app'),artifact/'bin'/x.app)
  need(source(root)==initial and sha(tool/'sky')==official['binarySHA256'],'SourceOrCompilerChanged');passed=True
 finally:
  interrupt.begin_cleanup()
  try:owner.cleanup();cleanup=True
  except Exception:passed=False
  if guardlog:guardlog.close()
  passed=passed and cleanup and interrupt.first is None
  (out/'result.json').write_text(json.dumps({'passed':passed,'cleanup':cleanup,'phases':phases,'applicationLaunched':False})+'\n')
 if passed:
  facts={str(p.relative_to(artifact)):{'sha256':sha(p),'bytes':p.stat().st_size,'mode':oct(p.stat().st_mode&0o777)} for p in artifact.rglob('*') if p.is_file()}
  (artifact/'provenance.json').write_text(json.dumps({'passed':True,'cleanup':True,'sourceCommit':x.head,'sourceFiles':initial,'compiler':official,'artifactFiles':facts,'applicationLaunched':False,'runtimeUserDataRead':False,'signing':'unsigned-or-ad-hoc; local existing identity required','scope':'compile plus existing safe suites only; no provider or live assistant validation'},indent=2)+'\n')
 print(json.dumps({'passed':passed,'cleanup':cleanup,'phaseCount':len(phases),'applicationLaunched':False}));return 0 if passed else 1
if __name__=='__main__':
 try:raise SystemExit(main())
 except Exception as e:print(json.dumps({'passed':False,'errorClass':type(e).__name__}));raise SystemExit(1)
