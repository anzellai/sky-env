# Parent registers a kernel NOTE_TRACK fork watcher and process-version handle
# BEFORE any supplied executable runs. No context/arguments are printed.
import os,sys
fd=int(sys.argv[1])
allowed=os.read(fd,1)
os.close(fd)
if allowed!=b'1':raise SystemExit(1)
os.execv(sys.argv[2],sys.argv[2:])
