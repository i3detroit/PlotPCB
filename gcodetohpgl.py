#!/usr/bin/env python

import sys
import re
import serial

# Protomat C30s steps per inch
calfactor = 3200
# steps per mm
# calfactor = 3200/25.4

# hard clip step limits: X 43836, Y 25565 

# in gcode units, so inches
xoff = 4
# registration pins sit at 10 cm
yoff = 10.25/2.54

with open(sys.argv[1],'rb') as f:
    number = 0

    ser = serial.Serial('/dev/ttyUSB0',9600,rtscts=True)
    ser.write("VS12000;!OC;!SV140;!SM32;!WR0,8,8;!CC;!CM1;!EM1;!OC;!RM32;!CC;")

    for line in f:
        number += 1
        #gcnote = re.match("\((.*)\)", line.strip())
        #if gcnote:
        #    print "note: " + gcnote.group(1)
        xycmd = re.match("G0[01] X(\S*) Y(\S*).*", line.strip())
        if xycmd:
            newx = int(calfactor * (xoff + float(xycmd.group(1))))
            newy = int(calfactor * (yoff + float(xycmd.group(2))))
            sys.stdout.write(str(number) + "\t" + line.strip() + "\t")
            sys.stdout.write("PA" + str(newx)  + "," + str(newy) + ";\n")
        zcmd = re.match("G0[01] Z(\S*).*", line.strip())
        if zcmd:
            newz = float(zcmd.group(1))
            if newz <= 0.0: 
                sys.stdout.write("\nPD;")
            if newz > 0.0:
               sys.stdout.write("PU;\n")
        newtool = re.match("M06 T([0-9]*) (\(.*\)).*", line.strip())
        if newtool:
            # spin down and home
            ser.write("OC;!RM0;!CC;!EM0;PA0,0;")
            sys.stdout.write("Insert " + newtool.group(2) + " diameter
                             drill\nPress enter when done.\n")
            raw_input()
            ser.write("OC;!RM32;!CC;!EM1;")
    ser.write(";!RM0;!CC;PU;!EM0;PA0,0;")
