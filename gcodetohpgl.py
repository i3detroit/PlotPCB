#!/usr/bin/env python

import sys
import re
import serial
import io
from tempfile import SpooledTemporaryFile as sptf
from argparse import ArgumentParser
from glob import glob
from os.path import join
from termcolor import colored, cprint
from time import sleep

#### Machine configuration ####
# default units for moves are inches
units = 'in'

# default mode for moves is absolute
mode = 'abs'

# Protomat C30s steps per inch
calfactor = 3200

# hard clip step limits
xmax = 43836
ymax = 25565

# board start offset in inches
xoff = 4
yoff = 102.5/25.4

# milling feed in um/s
mill_feed = 12000

# spindle speed in krpm [0..32]
spindle_speed = 32

# time to wait, in ms, for a drill to complete
drill_dwell = 700

# number of HPGL commands to buffer before waiting
serial_queue = 1

#### End machine details ####

#### Start parse functions ####
def change_units(new):
    '''Change units on machine parameters'''
    global units,calfactor,xoff,yoff
    if units == new:
        return
    if new == 'in':
        calfactor /= 25.4
        xoff /= 25.4
        yoff /= 25.4
    if new == 'mm':
        calfactor *= 25.4
        xoff *= 25.4
        yoff *= 25.4
    print 'Changed units from %s to %s'%(units,new)
    units = new

def change_mode(new):
    '''Change mode on machine parameters'''
    global mode
    hpgl = ''
    if mode == new:
        return hpgl
    if mode == 'rel':
        hpgl = 'OS;'+\
               '\nCO "wait for position response"\n'
    print 'Changed mode from %s to %s'%(mode,new)
    mode = new
    return hpgl

def parse_move(gcode):
    '''Parse a move command'''
    #TODO blindly initialising this to 0 is bad news bears.
    #       probably ought to query the machine for position, or ensure 'IN;'
    #       is run at the start of each file
    global mode, calfactor, xoff, yoff
    if not hasattr(parse_move,"x"):
        parse_move.x = 0
    if not hasattr(parse_move,"y"):
        parse_move.y = 0
    xycmd = re.match("G0[01] X(\S*) Y(\S*).*", gcode)
    if mode == 'abs':
        newx = int(calfactor * (xoff + float(xycmd.group(1))))
        newy = int(calfactor * (yoff + float(xycmd.group(2))))
        if newx > xmax:
            sys.stderr.write('X move bigger than bed! (%d > %d)\n'%(newx,xmax))
            sys.exit(12)
        if newy > ymax:
            sys.stderr.write('Y move bigger than bed! (%d > %d)\n'%(newy,ymax))
            sys.exit(12)
        hpgl = 'PA%d,%d;'%(newx,newy)
    elif mode == 'rel':
        newx = int(calfactor * (float(xycmd.group(1))))
        newy = int(calfactor * (float(xycmd.group(2))))
        if parse_move.x + newx > xmax:
            sys.stderr.write('X move bigger than bed! (%d > %d)\n'\
                             %(newx,xmax))
            sys.exit(12)
        if parse_move.y + newy > ymax:
            sys.stderr.write('Y move bigger than bed! (%d > %d)\n'\
                             %(parse_move.y + newy,ymax))
            sys.exit(12)
        hpgl = 'PR%d,%d;'%(parse_move.x + newx,parse_move.y + newy)
    parse_move.x += newx
    parse_move.y += newy
    return hpgl

def parse_z(gcode,drill):
    '''Parse a Z command'''
    global drill_dwell
    zcmd = re.match("G0[01] Z(\S*).*", gcode)
    newz = float(zcmd.group(1))
    if newz <= 0.0: 
       hpgl = 'PD;'
       if drill:
           hpgl += '!TW%s;'%drill_dwell
    if newz > 0.0:
       hpgl = 'PU;'
    return hpgl

def parse_tool_change(gcode):
    '''Parse a tool-change command'''
    global spindle_speed
    newtool = re.match("M06 T([0-9]*) \((.*)\).*", gcode)
    hpgl = '!OC;!RM0;!CC;!EM0;PA0,0;'+\
           '\nCO "insert tool %s: size '%newtool.group(1).strip() + newtool.group(2).strip() + '"' +\
           '\n!OC;!RM%d;!CC;!EM1;'%spindle_speed
    return hpgl

def parse_line(line,drill):
    '''Parse a line of GCODE'''
    hpgl = ''
    if line.startswith('G20'):
        # inch units
        change_units('in')
    elif line.startswith('G21'):
        # mm units
        change_units('mm')
    elif line.startswith('G90'):
        # absolute moves
        hpgl = change_mode('abs')
    elif line.startswith('G91'):
        # relative moves
        hpgl = change_mode('rel')
    elif line.startswith('G00') or line.startswith ('G01'):
        # move of some sort
        if 'Z' in line:
            # Z move
            hpgl = parse_z(line,drill)
        else:
            # XY move
            hpgl = parse_move(line)
    elif line.startswith('G04'):
        # dwell
        pass
    elif line.startswith('M03'):
        # start spindle
        pass
    elif line.startswith('M05'):
        # stop spindle
        pass
    elif line.startswith('M06'):
        # tool change
        hpgl = parse_tool_change(line)
    return hpgl

#### End parse functions ####

#### Start control functions ####
def tool_change(hpgl):
    '''Change tools'''
    drill = hpgl[hpgl.find('"')+1:hpgl.rfind(' ')]
    raw_input('Insert %s" diameter drill\nPress enter when done.')

#### End control functions ####

def main():
    '''Main program routine'''
    #### Set up command-line arguments and usage instructions ####
    parser = ArgumentParser(description='Converts EAGLE GCODE (from '
                            'http://pcbgcode.com) into LPKF HGPL, and runs the '
                            'machine', usage='%(prog)s [options] DIR')
    parser.add_argument('gcode_dir',metavar='DIR',default='./',
                        help='directory in which the gcode files reside')
    parser.add_argument('-o','--output',metavar='FILE',dest='save_hpgl',default='$$$$TEMP$$$$',
                        help='save the HPGL output in the given location (defaults to a temp file)')
    parser.add_argument('-f','--file',dest='file', default='',
                        help='which file prefix to use out of the gcode files in the directory')
    ser_opts = parser.add_argument_group('serial port options')
    ser_opts.add_argument('-p','--port',dest='port',default='/dev/ttyUSB0',
                        help='serial port (default /dev/ttyUSB0)')
    ser_opts.add_argument('-b','--baud',dest='baud',default=9600,type=int,
                        help='baudrate (default 9600)')
    
    args = parser.parse_args()
    
    #### End CLI arguments ####

    #### Start GCODE parse and HPGL generation ####
    # find the correct GCODE files
    print '%s Start GCODE Processing %s'%('-'*28,'-'*28)
    drills = glob(join(args.gcode_dir,args.file + '*drill.g'))
    routes = glob(join(args.gcode_dir,args.file + '*etch.g'))
    mills = glob(join(args.gcode_dir,args.file + '*.g'))
    mills = list(set(mills) - set(drills) - set(routes))
    
    if len(drills) > 1:
        sys.stderr.write('Multiple drill files selected, too confusing!\n\t')
        sys.stderr.write('\n\t'.join(drills) + '\n')
        sys.exit(10)
    
    layer = drills[0][-11:-8]
    
    print 'Using layer %s as first layer based on drill file.'%layer 
    print 'Machine is on %s at %dbaud'%(args.port,args.baud)
    print 'Machine will mill at %dum/s and spin up to %drpm.'\
            %(mill_feed,spindle_speed*1000)
    print 'Board offset is X=%.6f%s, Y=%.6f%s, max bed is X=%.2f%s, Y=%.2f%s'\
            %(xoff,units,yoff,units,xmax/calfactor,units,ymax/calfactor,units)
    print 'Board will be milled in %s mode and use %s as units'%(mode,units)
    
    # determine if we need a temp file or a real one
    hpgl_file = None
    if args.save_hpgl == '$$$$TEMP$$$$':
        hpgl_file = sptf(max_size=10000000)
        print 'Producing HPGL output in tempfile'
    else:
        hpgl_file = open(args.save_hpgl,'w+b')
        print 'Producing HPGL output in %s'%args.save_hpgl

    # drills first
    with open(drills[0]) as f:
        print '%s Drills %s'%('='*36,'='*36)
        number = 0
    
        hpgl_file.write('IN;!CT1;VS%d;!OC;!SV140;!SM32;!WR0,8,8;!CC;!CM1;!EM1;!OC;!RM%d;!CC;'%(mill_feed,spindle_speed))
    
        for line in f:
            line = line.strip()
            if line.startswith('('):
                #comment
                continue
            hpgl = parse_line(line,drill=True)
            number += 1
            print '%d\t%s\t%s%s'%(number,line,('','\t')[len(line)<16],hpgl)
            hpgl_file.write(hpgl)
        print '%s End Drills %s'%('='*34,'='*34)

    hpgl_file.write('!OC;!RM0;!CC;PU;!EM0;PA0,0;')

    #### End HPGL generation ####

    #### Serial output (machine control) ####
    if args.save_hpgl == '$$$$TEMP$$$$':
        ser = serial.Serial(args.port,args.baud,rtscts=True)
        ser.read(ser.inWaiting())
        queued = 0
        hpgl_file.seek(0, 0)
        for line in hpgl_file.read().split('\n'):
            print repr(line.strip())
            for command in line.split(";"):
            	if command:
                    comment = re.match("CO \"(.*)\"", command)
                    if comment:
                        raw_input(colored(comment.group(1), 'magenta'))
                    elif 'RM' in command:
                        ser.write(command  + ';')
                        while ser.inWaiting() == 0:
                            sleep(0.01)
                        code = ser.read(ser.inWaiting())
                        match = True
                        while match:
                            print code
                            ser.write(command  + ';')
                            while ser.inWaiting() == 0:
                                sleep(0.01)
                            newcode = ser.read(ser.inWaiting())
                            match = (code == newcode)
                    else:
                        ser.write(command + ";")
                        queued += 1
                        if command not in ('!OC','!WR0,8,8'):
                            while ser.inWaiting() == 0:
                                sleep(1)
                        print colored(command, 'red'),colored('%r'%ser.read(ser.inWaiting()),'yellow')
        print('Wait until plotter finishes and press enter to exit')
        raw_input()
    #### End Machine control ####

if __name__ == '__main__':
    main()
