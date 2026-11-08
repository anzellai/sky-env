"""Reentrancy-safe interruption: signals never interrupt owned cleanup."""
import signal
class Interruption:
 def __init__(self):self.first=None;self.repeats=0;self.cleaning=False
 def install(self):
  for name in ['SIGTERM','SIGINT','SIGHUP']:signal.signal(getattr(signal,name),self.handle)
 def handle(self,number,frame):
  if self.first is not None:self.repeats+=1;return
  self.first=number
  if not self.cleaning:raise KeyboardInterrupt()
 def begin_cleanup(self):self.cleaning=True
 def resume_work(self):
  self.raise_if_requested();self.cleaning=False
 def raise_if_requested(self):
  if self.first is not None:raise KeyboardInterrupt()
