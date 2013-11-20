#!/usr/bin/env python

import sys
import serial

ser = serial.Serial('/dev/ttyUSB0',9600,rtscts=True)
with open(sys.argv[1],'rb') as f:
	d = f.read(512)
	while d:
		print d
		ser.write(d)
		raw_input()
		d = f.read(512)
