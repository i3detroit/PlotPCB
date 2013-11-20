PlotPCB
=======

Converts PCB2GCODE output to the LPKF Protomat's dialect of HPGL.

The intention of this project is to allow users of older machines (such as the C30/S at i3Detroit) to make use of the machine without needing an old copy of Windows and an even older copy of the official LPKF control software. Instead, since the PCB mill thinks it is a plotter and largely talks standard HPGL, this project will take the GCODE generated by http://www.pcbgcode.org/ and turn it into sensible HPGL, then drip-feed the machine with it with user prompts for tool changes and the like.

Requirements
=============

* [EAGLE](http://cadsoftusa.com)
* [PCB-GCODE](http://www.pcbgcode.org/)
