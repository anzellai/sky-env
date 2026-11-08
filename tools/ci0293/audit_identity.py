"""Darwin process identity handles. Never inspect command lines/environment.
Signals use the kernel-checked audit token (PID + process version), not kill(pid).
"""
import ctypes,errno
class IdentityError(Exception):pass
class Token(ctypes.Structure):
 _fields_=[('val',ctypes.c_uint32*8)]
 def key(self):return tuple(self.val)
lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
proc=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
self_port=ctypes.c_uint.in_dll(lib,'mach_task_self_').value
lib.task_name_for_pid.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.POINTER(ctypes.c_uint)]
lib.task_name_for_pid.restype=ctypes.c_int
lib.task_info.argtypes=[ctypes.c_uint,ctypes.c_int,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_uint)]
lib.task_info.restype=ctypes.c_int
lib.mach_port_deallocate.argtypes=[ctypes.c_uint,ctypes.c_uint]
proc.proc_signal_with_audittoken.argtypes=[ctypes.POINTER(Token),ctypes.c_int]
proc.proc_signal_with_audittoken.restype=ctypes.c_int
def capture(pid):
 port=ctypes.c_uint()
 if lib.task_name_for_pid(self_port,int(pid),ctypes.byref(port))!=0:return None
 try:
  token=Token();count=ctypes.c_uint(8)
  result=lib.task_info(port.value,15,token.val,ctypes.byref(count))
  if result!=0 or count.value!=8 or token.val[5]!=pid:return None
  return token
 finally:lib.mach_port_deallocate(self_port,port.value)
def send(token,signal):
 code=proc.proc_signal_with_audittoken(ctypes.byref(token),int(signal))
 if code==errno.ESRCH:return False
 if code:raise IdentityError('identity-safe signal failed')
 return True
def alive(token):
 current=capture(token.val[5]);return current is not None and current.key()==token.key()

class Unique(ctypes.Structure):
 _fields_=[('uuid',ctypes.c_ubyte*16),('unique',ctypes.c_uint64),('parent_unique',ctypes.c_uint64),('version',ctypes.c_int32),('original_parent_version',ctypes.c_int32),('reserved2',ctypes.c_uint64),('reserved3',ctypes.c_uint64)]
class Short(ctypes.Structure):
 _fields_=[('pid',ctypes.c_uint32),('ppid',ctypes.c_uint32),('pgid',ctypes.c_uint32),('status',ctypes.c_uint32),('ignored_comm',ctypes.c_char*16),('flags',ctypes.c_uint32),('uid',ctypes.c_uint32),('gid',ctypes.c_uint32),('ruid',ctypes.c_uint32),('rgid',ctypes.c_uint32),('svuid',ctypes.c_uint32),('svgid',ctypes.c_uint32),('reserved',ctypes.c_uint32)]
proc.proc_pidinfo.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int]
proc.proc_pidinfo.restype=ctypes.c_int
proc.proc_listallpids.argtypes=[ctypes.c_void_p,ctypes.c_int]
proc.proc_listallpids.restype=ctypes.c_int
def info(pid):
 u=Unique();s=Short()
 if proc.proc_pidinfo(pid,17,1,ctypes.byref(u),ctypes.sizeof(u))!=ctypes.sizeof(u):return None
 if proc.proc_pidinfo(pid,13,1,ctypes.byref(s),ctypes.sizeof(s))!=ctypes.sizeof(s):return None
 return u,s
def pids():
 size=proc.proc_listallpids(None,0)+128
 if size<1 or size>32768:raise IdentityError('process metadata enumeration bound')
 buffer=(ctypes.c_int*size)();count=proc.proc_listallpids(buffer,ctypes.sizeof(buffer))
 if count<0 or count>=size:raise IdentityError('incomplete process metadata enumeration')
 return [int(x)for x in buffer[:count]if x>0]
def verified(pid):
 before=info(pid)
 if before is None:return None
 token=capture(pid);after=info(pid)
 if token is None or after is None:return None
 if before[0].unique!=after[0].unique or token.val[7]!=(after[0].version&0xffffffff):return None
 return token,after[0],after[1]
