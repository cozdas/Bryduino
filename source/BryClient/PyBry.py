'''
PyBry: Brymen DMM data connection client


Sample data layout
sample
    timestamp
    inbytes
    state
    measureUpper   
    measureLower
'''

#for Brymen connection
import serial
import time

#for graphing
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
import numpy as np


#Some constants
PortName            = 'Com9'
Nread               = 20
WatchdogResetPeriod = 60 #seconds
DebugOn             = True


#globals
logSamples = []
logGraphDataU = np.empty(100)
logGraphDataL = np.empty(100)

def AddSampleToHistory(sample):
    global logSamples
    global logGraphDataU
    global logGraphDataL

    logSamples.append(sample)
    
    #grow graph data by 2x
    size = len(logSamples)
    if size >= logGraphDataU.shape[0]:
        tmp = logGraphDataU
        logGraphDataU = np.empty(2*logGraphDataU.shape[0])
        logGraphDataU[:tmp.shape[0]] = tmp
        
    if size >= logGraphDataL.shape[0]:
        tmp = logGraphDataL
        logGraphDataL = np.empty(2*logGraphDataL.shape[0])
        logGraphDataL[:tmp.shape[0]] = tmp
        
    logGraphDataL[size-1] = sample["measureLower"]["value"]
    logGraphDataU[size-1] = sample["measureUpper"]["value"]
    #print(sample)


#Segment data to character map (7 MSB only)
segments ={
    0b10111110:"0",
    0b10100000:"1",
    0b11011010:"2",
    0b11111000:"3",
    0b11100100:"4",
    0b01111100:"5",
    0b01111110:"6",
    0b10101000:"7",
    0b11111110:"8",
    0b11111100:"9",
    0b00000000:" ",
    0b01000000:"-",
    0b01001110:"F",
    0b00011110:"C",
    0b00010110:"L",
    0b11110010:"d",
    0b00100000:"i",
    0b01110010:"o",
    0b01011110:"E",
    0b01000010:"r",
    0b01100010:"n",
    }


def PrintMeasurement(meas):
    print("{:.6g} {} = {:.6f} {} ({}) ".format( meas["value"],  meas["unit"], meas["valueOrg"],  meas["unitOrg"],  meas["source"]), end="")

def PrintSample(sample, unpackedData):
    inbytes = sample["inbytes"]
    
    UnpackLower   = unpackedData["lower"]
    UnpackUpper   = unpackedData["upper"]
    hexs = ":".join("{:02x}".format(c) for c in inbytes)
    
    #raw data
    if DebugOn:
        print("{} --> {} {}".format(hexs, ''.join(UnpackLower["Segs"]), ''.join(UnpackUpper["Segs"])))
    
    #upper measurement
    PrintMeasurement(sample["measureUpper"])
    if DebugOn:
        print(GetLitItems(UnpackUpper))
    
    #lower measurement
    PrintMeasurement(sample["measureLower"])
    if DebugOn:
        print(GetLitItems(UnpackLower))
        #common state
        print(GetLitItems(unpackedData))
 
    print("") #newline


def GetLitItems(pack):
    litItems = [key for key, val in pack.items() if val==True] 
    return litItems

def DecodeDigit(char):
    digit = char & 0b11111110
    if digit in segments:
        return segments[digit]
    return '?'

#decodes the number, unit and source using the unpacked display info
def DecodeMeasurement(unpackedDisplay):
    measure = {}

    if "Segs" not in unpackedDisplay:
        return None

    lit = GetLitItems(unpackedDisplay)

    unit = ""
    #convert to string
    s = ''.join(unpackedDisplay["Segs"])

    #insert decimal point    
    dotPos = None
    if "Dec1" in lit: dotPos=1
    if "Dec2" in lit: dotPos=2
    if "Dec3" in lit: dotPos=3
    if "Dec4" in lit: dotPos=4
    if dotPos!=None:
        s = s[:dotPos] + '.' + s[dotPos:]

    measure["text"] = s

    #determine Unit
    if   "A"   in lit: unit = "A"
    elif "V"   in lit: unit = "V"
    elif "Ohm" in lit: unit = "Ω"
    elif "Hz"  in lit: unit = "Hz"
    elif "F"   in lit: unit = "F"
    elif "S"   in lit: unit = "S"
    elif "Duty" in lit: unit = "%"
    elif "dB"  in lit: unit = "dBm"

    #remove F or C
    if s[-1:] in ["F", "C"]: 
        unit = "°" + s[-1:]
        s = s[:-1]

    unitOrg = unit

    #determine multiplier
    mult = 1.0
    if "dB" not in lit:
        if "n" in lit: 
            mult=1e-9
            unitOrg = "n"+unit
        if "µ" in lit: 
            mult=1e-6
            unitOrg = "µ"+unit
        if "m" in lit: 
            mult=1e-3
            unitOrg = "m"+unit
        if "k" in lit: 
            mult=1e3
            unitOrg = "k"+unit
        if "M" in lit: 
            mult=1e6
            unitOrg = "M"+unit

    #convert to float
    try:
        valf = float(s)
        if "Neg" in lit: 
            valf = -valf
    except ValueError:
        valf = float('nan')

    #Source
    source = ""
    if "DC" in lit and "AC" in lit: source = "DC+AC"
    elif "DC" in lit: source = "DC"
    elif "AC" in lit: source = "AC"
    elif "F" in lit: source = "Capacitance"
    elif "Ohm" in lit: source = "Resistance"
    elif "S" in lit: source = "Conductance"
    elif "Hz" in lit: source = "Frequency"
    elif "Duty" in lit: source = "Duty"
    
    if "TempDiff" in lit: source = "Temperature Diff"
    elif "T1" in lit: source = "Temperature 1"
    elif "T2" in lit: source = "Temperature 2"

    if unit=="A": source += " Current"
    if unit=="V": source += " Voltage"

    valDerived = valf;
    if unitOrg=="nS":
        unit="Ω"
        valDerived=1e9/valf
    else:
        valDerived=mult*valf

    #pack the result
    measure["value"] = valDerived
    measure["unit"] = unit
    measure["valueOrg"] = valf
    measure["unitOrg"] = unitOrg
    measure["source"] = source
    
    return measure
       
#using the unpacked bits, determines the current state including the measurements
def DecodeUnpackedData(unpackedData):
    lit = GetLitItems(unpackedData) #get lit items in the common (non-value-specific) section

    state = {}

    state["Holding"] = "Hold" in lit
    state["Relative"]= "Delta" in lit
    state["Recording"]= "Record" in lit
    state["Crest"]= "Crest" in lit
    state["Min"]= "Min" in lit and ("Max" not in lit)
    state["Max"]= "Max" in lit and ("Min" not in lit)
    state["Avg"]= "Avg" in lit and ("Min" not in lit)

    #decode the upper and lower measurements
    measureUpper = DecodeMeasurement(unpackedData["upper"])
    measureLower = DecodeMeasurement(unpackedData["lower"])

    #cross-display fixes
    if measureUpper["text"]=="diod":
        measureLower["source"] = "Diode" + measureLower["source"]

    if "Temperature" in measureUpper["source"]:
        measureUpper["unit"]    = measureLower["unit"]
        measureUpper["unitOrg"] = measureLower["unitOrg"]

    return (state, measureUpper, measureLower)
    
#unpacks the bits in the bytearray to named flags and digit character array
def UnpackBytes(inbytes):
    unpack = {"lower":{}, "upper":{}}
    lower = unpack["lower"]
    upper = unpack["upper"]

    def UnpackBit(dic, byte, bit, key):
        dic[key] = (inbytes[byte]&(1<<bit))!=0

    #Byte0
    UnpackBit(unpack, 0, 0, "Auto")
    UnpackBit(unpack, 0, 1, "Record")
    UnpackBit(unpack, 0, 2, "Crest")
    UnpackBit(unpack, 0, 3, "Hold")
    UnpackBit(lower,  0, 4, "DC")
    UnpackBit(unpack, 0, 5, "Max")
    UnpackBit(unpack, 0, 6, "Min")
    UnpackBit(unpack, 0, 7, "Avg")

    #Byte1
    UnpackBit(lower,  1, 0, "AC")
    UnpackBit(lower,  1, 1, "T1")
    UnpackBit(lower,  1, 2, "TempDiff")
    UnpackBit(lower,  1, 3, "T2")
    UnpackBit(unpack, 1, 4, "BarScale")
    UnpackBit(unpack, 1, 5, "BarNeg")
    UnpackBit(lower,  1, 6, "VFD")
    UnpackBit(lower,  1, 7, "Neg")

    #Byte2
    UnpackBit(lower,  2, 0, "Delta")

    #Byte7
    UnpackBit(lower,  7, 0, "V")

    #Byte8
    UnpackBit(upper,  8, 0, "µ")
    UnpackBit(upper,  8, 1, "m")
    UnpackBit(upper,  8, 2, "A")
    UnpackBit(upper,  8, 3, "system")
    UnpackBit(upper,  8, 4, "Neg")
    UnpackBit(upper,  8, 5, "AC")
    UnpackBit(upper,  8, 6, "T2")
    UnpackBit(unpack, 8, 7, "Batt")

    #Byte9
    UnpackBit(unpack,  9, 0, "Cont")

    #Byte13
    UnpackBit(upper, 13, 0, "M")
    UnpackBit(upper, 13, 1, "k")
    UnpackBit(upper, 13, 2, "Hz")
    UnpackBit(upper, 13, 3, "V")
    UnpackBit(lower, 13, 4, "S")
    UnpackBit(lower, 13, 5, "F")
    UnpackBit(lower, 13, 6, "n")
    UnpackBit(lower, 13, 7, "A")

    #Byte14
    UnpackBit(lower, 14, 0, "Hz")
    UnpackBit(lower, 14, 1, "dB")
    UnpackBit(lower, 14, 2, "m")
    UnpackBit(lower, 14, 3, "µ")
    UnpackBit(lower, 14, 4, "Ohm")
    UnpackBit(lower, 14, 5, "M")
    UnpackBit(lower, 14, 6, "k")
    UnpackBit(lower, 14, 7, "Duty")

    #Decimal Points
    UnpackBit(lower, 3, 0, "Dec1")
    UnpackBit(lower, 4, 0, "Dec2")
    UnpackBit(lower, 5, 0, "Dec3")
    UnpackBit(lower, 6, 0, "Dec4")
    
    UnpackBit(upper, 10, 0, "Dec1")
    UnpackBit(upper, 11, 0, "Dec2")
    UnpackBit(upper, 12, 0, "Dec3")

    #upper segs
    upper["Segs"]=[]
    for digit in range(0, 4):
        upper["Segs"].append(DecodeDigit(inbytes[9+digit]))

    #lower segs
    lower["Segs"]=[]
    for digit in range(0, 6):
        lower["Segs"].append(DecodeDigit(inbytes[2+digit]))

    return unpack

def ResetWatchdog(ser):
    ser.write("Go".encode())
    nextWatchdogReset = time.time() + WatchdogResetPeriod
    if DebugOn:    
        print("*********Watchdog Reset**********")
    return nextWatchdogReset

    
def SampleLoop(ser):
    #flush the input buffer
    ser.reset_input_buffer()

    nextWatchdogReset = ResetWatchdog(ser)

    #Main loop: sample and reset watchdog
    while True:
        if ser.in_waiting >=Nread:
            #read the raw bytes
            inbytes = ser.read(Nread)
            sample = {"inbytes":inbytes, "timestamp":time.time()}
            
            #unpack the bits and 7 segment data
            unpackedData = UnpackBytes(inbytes)
            
            #decode the unpacked data to meaninful states and measurements with units
            sample["state"], sample["measureUpper"], sample["measureLower"] = DecodeUnpackedData(unpackedData)
            
            #record and display
            PrintSample(sample, unpackedData)
            AddSampleToHistory(sample)
        
        #if time to reset watchdog, do it
        if time.time() > nextWatchdogReset:
            nextWatchdogReset = ResetWatchdog(ser)
        time.sleep(0.01)

def UpdateGraph():
    global curveU
    global plU
    global curveL
    global plL
    global logSamples
    global logGraphDataU
    global logGraphDataL
    
    size = len(logSamples)

    if size>0:

        curveL.setData(logGraphDataL[:size])
        label = logSamples[size-1]["measureLower"]["source"]
        unit =  logSamples[size-1]["measureLower"]["unit"]
        plL.getAxis('left').setLabel(label, unit)
        plL.setTitle(label)

        curveU.setData(logGraphDataU[:size])
        label = logSamples[size-1]["measureUpper"]["source"]
        unit =  logSamples[size-1]["measureUpper"]["unit"]
        plU.getAxis('left').setLabel(label, unit)
        plU.setTitle(label)



def InitGraph():
    global win
    global curveU
    global plU
    global curveL
    global plL

    win = pg.GraphicsWindow()
    win.setWindowTitle('PyBry')

    plU = win.addPlot()
    plU.setDownsampling(mode='mean')
    plU.getAxis('left').setGrid(128)
    plU.getAxis('left').enableAutoSIPrefix(True)
    plU.getAxis('bottom').setGrid(128)
    plU.setClipToView(True)
    curveU = plU.plot()

    win.nextRow()

    plL = win.addPlot()
    plL.setDownsampling(mode='mean')
    plL.getAxis('left').setGrid(128)
    plL.getAxis('left').enableAutoSIPrefix(True)
    plL.getAxis('bottom').setGrid(128)
    plL.setClipToView(True)
    curveL = plL.plot()

    plL.setXLink(plU)
    plU.setXLink(plL)


    
class SamplingThread(QtCore.QThread):
    def __init__(self):
        QtCore.QThread.__init__(self)

    def __del__(self):
        self.wait()

    def run(self):
        with serial.Serial(PortName) as ser:
            print(ser)
            SampleLoop(ser)


if __name__ == "__main__":
    import sys
    #app = QtGui.QApplication([])

    #init graph
    InitGraph()

    #setup update timer
    timer = QtCore.QTimer()
    timer.timeout.connect(UpdateGraph)
    timer.start(50)

    #run the background sampling thread 
    samplingThread = SamplingThread()
    samplingThread.start()

    #run the application
    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtGui.QApplication.instance().exec_()
