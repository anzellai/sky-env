"""Darwin-owned subprocess trees, with identity-safe descendant cleanup.
No process argv/environment inspection. Only registered native identities are
signalled. Polling discovery is best-effort, NEVER a complete descendant claim.
Unexpected service/worker exit fails the run and leaves descendant cleanup
unverified, even after all registered processes terminate.
"""
from pathlib import Path
import os,select,signal,subprocess,sys,threading,time
from audit_identity import IdentityError,alive,info,pids,send,verified
class OwnershipError(Exception):pass
class Owner:
 def __init__(self):
  self.children=[];self.records={};self.roots={};self.pending={};self.failed=False;self.unexpected=False
  self.lock=threading.RLock();self.queue=select.kqueue();self.done=threading.Event()
  self.thread=threading.Thread(target=self._watch,daemon=True);self.thread.start()
 def _record(self,pid,root,parent=None):
  value=verified(pid)
  if value is None:return False
  token,u,s=value
  if parent is not None:
   known=[r for r in self.records.values()if r['pid']==parent and r['root']==root]
   if not any(u.parent_unique==r['unique']for r in known):return False
  existing=self.records.get(u.unique)
  versions=set()if existing is None else existing['versions']
  versions.add(token.val[7])
  self.records[u.unique]={'pid':pid,'unique':u.unique,'root':root,'token':token,'versions':versions}
  return True
 def _events(self):
  try:events=self.queue.control(None,512,0)
  except OSError:self.failed=True;return
  for event in events:
   flags=event.fflags;pid=int(event.ident)
   if flags&select.KQ_NOTE_TRACKERR:self.failed=True
   root=int(event.udata or 0)
   if not root:continue
   if flags&select.KQ_NOTE_CHILD:self.pending[(pid,root)]=int(event.data)
   if flags&select.KQ_NOTE_EXEC:
    known=[r for r in self.records.values()if r['pid']==pid and r['root']==root]
    current=verified(pid)
    if current:
     token,u,_=current
     for record in known:
      if record['unique']==u.unique:record['token']=token;record['versions'].add(token.val[7])
   if flags&select.KQ_NOTE_EXIT:
    # The kernel watcher is bound to the exiting process object. A different
    # process later using this PID is never adopted/signalable by this event.
    self.pending.pop((pid,root),None)
 def discover(self):
  with self.lock:
   self._events()
   for child in self.children:
    if not getattr(child,'_stopping',False)and child.poll()is not None and(not getattr(child,'_expected_exit',False)or(getattr(child,'_expected_exit',False)!='command'and child.returncode!=0)):self.unexpected=True
   for _ in range(8):
    changed=False
    for(pid,root),parent in list(self.pending.items()):
     if self._record(pid,root,parent):self.pending.pop((pid,root),None);changed=True
     else:
      current=info(pid)
      if current is None or current[1].status==5:self.pending.pop((pid,root),None)
    # Parent-unique metadata recovers detached/reparented descendants even
    # after a leader exits; native fork tracking covers intermediate deaths.
    for pid in pids():
     current=info(pid)
     if current is None:continue
     u,s=current
     known=self.records.get(u.unique)
     if known and s.status!=5:
      current=verified(pid)
      if current and current[1].unique==known['unique']:
       known['token']=current[0];known['versions'].add(current[0].val[7])
     parent=self.records.get(u.parent_unique)
     if parent and u.unique not in self.records and s.status!=5:
      if self._record(pid,parent['root'],parent['pid']):changed=True
    if not changed:break
 def _watch(self):
  while not self.done.wait(.02):
   try:self.discover()
   except Exception:self.failed=True
 def start(self,args,cwd,context,output=subprocess.PIPE,*,input_pipe=False,text=False,stderr=subprocess.STDOUT,expected_exit=False):
  read,write=os.pipe();child=None
  try:
   child=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('spawn-gate.py')),str(read),*args],cwd=cwd,env=context,stdin=subprocess.PIPE if input_pipe else subprocess.DEVNULL,stdout=output,stderr=stderr,text=text,start_new_session=True,pass_fds=(read,))
   os.close(read);read=-1
   with self.lock:
    current=verified(child.pid)
    if current is None:raise OwnershipError('root identity prerequisite')
    token,u,_=current;root=u.unique;child._expected_exit=expected_exit;child._stopping=False;self.roots[id(child)]=root
    self.records[u.unique]={'pid':child.pid,'unique':u.unique,'root':root,'token':token,'versions':{token.val[7]}}
    event=select.kevent(child.pid,filter=select.KQ_FILTER_PROC,flags=select.KQ_EV_ADD|select.KQ_EV_ENABLE|select.KQ_EV_CLEAR,fflags=select.KQ_NOTE_FORK|select.KQ_NOTE_EXEC|select.KQ_NOTE_EXIT,udata=root)
    self.queue.control([event],0,0);self.children.append(child)
   os.write(write,b'1');return child
  except Exception:
   os.close(write);write=-1
   if child is not None:
    child.wait(timeout=2)
   raise
  finally:
   if read>=0:os.close(read)
   if write>=0:os.close(write)
 def command(self,args,cwd,context,timeout,input=None):
  child=self.start(args,cwd,context,input_pipe=True,text=True,stderr=subprocess.PIPE,expected_exit='command')
  try:stdout,_=child.communicate(input,timeout=timeout)
  except subprocess.TimeoutExpired:self.stop(child);raise OwnershipError('owned command deadline')from None
  status=child.returncode;self.stop(child)
  if status:raise OwnershipError('owned command failed')
  return stdout
 def _live(self,root):
  self.discover()
  return [record for record in self.records.values()if record['root']==root and alive(record['token'])]
 def stop(self,child,pg=False):
  root=self.roots.get(id(child))
  if root is None:raise OwnershipError('unregistered process')
  with self.lock:
   self.discover();child._stopping=True;records=self._live(root)
  leader=next((r for r in records if r['pid']==child.pid),None)
  if leader:send(leader['token'],signal.SIGINT if pg else signal.SIGTERM)
  else:
   for record in records:send(record['token'],signal.SIGTERM)
  deadline=time.monotonic()+(12 if pg else 5)
  while time.monotonic()<deadline:
   with self.lock:records=self._live(root)
   if not records:break
   time.sleep(.03)
  # Numeric group IDs are NEVER signalled, even if a leader has exited. Audit
  # token signals keep PID reuse outside the target in the kernel itself.
  deadline=time.monotonic()+3
  while True:
   with self.lock:records=self._live(root)
   if not records:break
   if time.monotonic()>deadline:raise OwnershipError('owned survivors remain')
   for record in records:send(record['token'],signal.SIGKILL)
   time.sleep(.03)
  try:child.wait(timeout=2)
  except subprocess.TimeoutExpired:raise OwnershipError('owned leader unreaped')from None
  with self.lock:
   self.discover()
   if self.failed or any(r==root for _,r in self.pending):raise OwnershipError('incomplete descendant tracking')
   if self._live(root):raise OwnershipError('owned survivors remain')
   if child in self.children:self.children.remove(child)
 def cleanup(self):
  error=False
  for child in list(reversed(self.children)):
   try:self.stop(child,pg=getattr(child,'_owned_pg',False))
   except Exception:error=True
  self.done.set();self.thread.join(timeout=2)
  if self.thread.is_alive():error=True
  self.queue.close()
  if error or self.failed:raise OwnershipError('registered process cleanup incomplete')
  if self.unexpected:raise OwnershipError('unexpected exit; descendant cleanup unverified')
