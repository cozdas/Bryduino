''' 
====================================================
PyBry: Brymen DMM data connection client v0.02
====================================================

Sample data layout
sample
    pctimestamp //received time wall clock
    timecode    //milliseconds since arduino boot (note: arduino reboots upon serial connection)
    inbytes
    state
    measureUpper   
    measureLower
'''

#for Brymen connection
import serial #pyserial
import time
import threading
import numpy as np


#for graphing
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui
from PyQt5.QtWidgets import QFileDialog
from pyqtgraph.dockarea import *
from datetime import timedelta


#Some constants
PORTNAME            = 'Com9'
Nread               = 24
WatchdogResetPeriod = 60 #seconds
DebugOn             = True
LinkAxes            = False


#====================================================================================
# Connection
#====================================================================================
class Connection:
    def __init__(self):
        self.portName = ''
        self.ser = None
        self.doRun = False
        self.killThread = False
        self.threadRunning = False
        self.runEvent = threading.Event()

    def Start(self, portTxtControl):
        #stop the thread and disconnect if another port is requested
        if portTxtControl.text() != self.portName:
            self.killThread = True
            self.runEvent.set()
            while(self.threadRunning):
                time.sleep(0.01)
            self.runEvent.clear()
            
        if not self.threadRunning:
            self.portName = portTxtControl.text()
            self.killThread = False
            thread = threading.Thread(target = self.OpenAndSample)
            thread.start()

        self.runEvent.set()
        #portTxtControl.setEnabled(False)
        
    def Stop(self):
        if self.ser!=None and self.ser.is_open:
            self.ser.write("[Stop]".encode())
            self.ser.flushOutput()
            time.sleep(0.1)
            self.ser.flushInput()
            self.runEvent.clear()

    def SetPeriod(self, periodTxtControl):
        if self.ser!=None and self.ser.is_open:
            cmd="[Per={}]".format(periodTxtControl.text())
            self.ser.write(cmd.encode())
            self.ser.flushOutput()
            time.sleep(0.1)
            self.ser.flushInput()


    def ResetWatchdog(self):
        self.ser.write("[Rst]".encode())
        self.nextWatchdogReset = time.time() + WatchdogResetPeriod
        if DebugOn:    
            print("*********Watchdog Reset**********")

    def OpenAndSample(self):
        self.threadRunning = True
        try:
            with serial.Serial(self.portName) as self.ser:
                self.SampleLoop()
        except serial.SerialException as e:
            print("Serial port Exception " + self.portName)
        finally:
            self.threadRunning = False

    def SampleLoop(self):
        global history

        #make sure DMM is not sending while we start so that we don't start packets in the midle.
        # turns out this is unnecessary as Arduino uno resets on serial connection
        self.ser.write("[Stop]".encode())
        self.ser.flushOutput()
        time.sleep(0.1)
        
        #flush the input buffer
        while self.ser.in_waiting>0:
            self.ser.write("[Stop]".encode())
            self.ser.reset_input_buffer()
            time.sleep(0.1)
        
        self.ResetWatchdog()

        decoder = BrymenDecoder()

        #Main loop: sample and reset watchdog
        while not self.killThread:
            if self.ser.in_waiting >=Nread:
                #read the raw bytes
                inbytes = self.ser.read(Nread)
                sample = {"inbytes":inbytes, "pctimestamp":time.time()}

                #make sure the data is not garbage
                if(inbytes[15:19]==b'\x86\x86\x86\x86'):
                    #unpack the bits and 7 segment data
                    unpackedData = decoder.UnpackBytes(inbytes)
            
                    #decode the unpacked data to meaninful states and measurements with units
                    sample["timecode"], sample["state"], sample["measureUpper"], sample["measureLower"] = decoder.DecodeUnpackedData(unpackedData)
            
                    #record and display
                    decoder.PrintSample(sample, decoder, unpackedData)
                    history.AddSampleToHistory(sample)
                else:
                    hexs = ":".join("{:02x}".format(c) for c in inbytes)
                    print("invalid data stream:", hexs)
        
            #if time to reset watchdog, do it
            if time.time() > self.nextWatchdogReset:
                self.ResetWatchdog()
            time.sleep(0.01)

            #if run event is cleared, stop the DMM and wait for the signal
            if not self.runEvent.isSet():
                #stop the DMM
                self.ser.write("[Stop]".encode())
                self.ser.flushOutput()
                #self.ser.reset_input_buffer()
                time.sleep(0.1)
                
                self.runEvent.wait()

                #start the DMM
                self.ser.write("[Go]".encode())
                self.ser.flushOutput()
                #self.ser.reset_input_buffer()
                time.sleep(0.1)

                


class SampleHistory:
    '''
    ====================================================================================
    SampleHistory: stores the individual samples in a python array. Simple x-y values
    are also stores in numpy arrays for direct consumption by the graph
    ====================================================================================
    '''
    def __init__(self):
        self.dataLock = threading.Lock()
        self.clearSampleHistory()
        

    def AddSampleToHistory(self, sample):
        with self.dataLock:
            self.logSamples.append(sample)
    
            #grow graph data by 2x
            sampleIdx = self.logGraphLen
            self.logGraphLen +=1 
            graphCapacity = self.logGraphData.shape[1]
            if self.logGraphLen >= graphCapacity:
                newData = np.empty((4,2*graphCapacity))
                newData[:,:graphCapacity] = self.logGraphData
                self.logGraphData = newData
    
            self.logGraphData[0,sampleIdx] = sample["timecode"]    
            self.logGraphData[1,sampleIdx] = sample["pctimestamp"]    
            self.logGraphData[2,sampleIdx] = sample["measureLower"]["value"]
            self.logGraphData[3,sampleIdx] = sample["measureUpper"]["value"]

            self.labels["lower"]["source"] = sample["measureLower"]["source"]
            self.labels["lower"]["unit"] = sample["measureLower"]["unit"]
            self.labels["upper"]["source"] = sample["measureUpper"]["source"]
            self.labels["upper"]["unit"] = sample["measureUpper"]["unit"]
            #print(sample)

    def clearSampleHistory(self):
        with self.dataLock:
            self.logSamples = [] #this effectively  resets the pointer
            self.logGraphData = np.empty((4,100))
            self.logGraphLen = 0
            self.labels = {"upper":{"source":"", "unit":""}, "lower":{"source":"", "unit":""}} 

    def exportCSV(self, fileName):
        with self.dataLock:
            headerStr = "Timecode (ms), WallClock (seconds), {} ({}), {} ({})".format(self.labels["lower"]["source"], self.labels["lower"]["unit"], self.labels["upper"]["source"], self.labels["upper"]["unit"])   
            headerStr = headerStr.replace('Ω', 'Ohm')
            np.savetxt(fileName, self.logGraphData[:,:self.logGraphLen].T, delimiter=",", fmt='%d,%f,%f,%f', header=headerStr)
        


        
          
#create an instance
history = SampleHistory()


class BrymenDecoder:
    '''
    ====================================================================================
    This class is able to unpack the raw byte array that the Brymen sends individual named
    bit and also decode those bits to meaningful DMM state and measurement values
    ====================================================================================
    '''
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

    def GetLitItems(self, pack):
        '''retuns a list of items whose bits are set to 1'''
        litItems = [key for key, val in pack.items() if val==True] 
        return litItems

    def DecodeDigit(self, char):
        '''some bytes have 7-segment bit field in the most significant bits. this function 
        decodes the most significant 7 bits to corresponding characters'''
        digit = char & 0b11111110
        if digit in self.segments:
            return self.segments[digit]
        return '?'

    def DecodeMeasurement(self, unpackedDisplay):
        '''decodes the unpacked 7-segment values, decimal point, units, sign bit, 
        etc to a complete measurement. Values are stored in base units as well as 
        in the units as measured by the DMM. (i.e. 0.00123V and 1.23 mV)
        '''
        measure = {}

        if "Segs" not in unpackedDisplay:
            return None

        lit = self.GetLitItems(unpackedDisplay)

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
    
        #add negative
        if "Neg" in lit:
            s = "-" + s

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
        measure["text"] = s
        measure["value"] = valDerived
        measure["unit"] = unit
        measure["valueOrg"] = valf
        measure["unitOrg"] = unitOrg
        measure["source"] = source
    
        return measure
       
    def DecodeUnpackedData(self, unpackedData):
        '''using the unpacked bits, determines the current state including the measurements
        '''
        lit = self.GetLitItems(unpackedData) #get lit items in the common (non-value-specific) section

        timecode = unpackedData["timecode"]

        state = {}

        state["Holding"] = "Hold" in lit
        state["Relative"]= "Delta" in lit
        state["Recording"]= "Record" in lit
        state["Crest"]= "Crest" in lit
        state["Min"]= "Min" in lit and ("Max" not in lit)
        state["Max"]= "Max" in lit and ("Min" not in lit)
        state["Avg"]= "Avg" in lit and ("Min" not in lit)

        #decode the upper and lower measurements
        measureUpper = self.DecodeMeasurement(unpackedData["upper"])
        measureLower = self.DecodeMeasurement(unpackedData["lower"])

        #cross-display fixes
        if measureUpper["text"]=="diod":
            measureLower["source"] = "Diode" + measureLower["source"]

        if "Temperature" in measureUpper["source"]:
            measureUpper["unit"]    = measureLower["unit"]
            measureUpper["unitOrg"] = measureLower["unitOrg"]

        return (timecode, state, measureUpper, measureLower)
    
    def UnpackBytes(self, inbytes):
        '''unpacks the bits in the bytearray to named flags and digit character array
        '''
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
            upper["Segs"].append(self.DecodeDigit(inbytes[9+digit]))

        #lower segs
        lower["Segs"]=[]
        for digit in range(0, 6):
            lower["Segs"].append(self.DecodeDigit(inbytes[2+digit]))

        timecode = (inbytes[23]<<24) +  (inbytes[22]<<16) + (inbytes[21]<<8) + (inbytes[20]);
        unpack["timecode"] = timecode
        

        return unpack
    
    def PrintMeasurement(self, meas):
        print("{:.6g} {} = {:.6f} {} ({}) ".format( meas["value"],  meas["unit"], meas["valueOrg"],  meas["unitOrg"],  meas["source"]), end="")

    def PrintSample(self, sample, decoder, unpackedData):
        inbytes = sample["inbytes"]
    
        UnpackLower   = unpackedData["lower"]
        UnpackUpper   = unpackedData["upper"]
        hexs = ":".join("{:02x}".format(c) for c in inbytes)
    
        #raw data
        if DebugOn:
            print("{} --> {} {}".format(hexs, ''.join(UnpackLower["Segs"]), ''.join(UnpackUpper["Segs"])))

        #time
        print("{} - {}".format(sample["timecode"],sample["pctimestamp"]))
        #upper measurement
        self.PrintMeasurement(sample["measureUpper"])
        if DebugOn:
            print(decoder.GetLitItems(UnpackUpper))
    
        #lower measurement
        self.PrintMeasurement(sample["measureLower"])
        if DebugOn:
            print(decoder.GetLitItems(UnpackLower))
            #common state
            print(decoder.GetLitItems(unpackedData))
 
        print("") #newline

class TimeAxisItem(pg.AxisItem):
    XAxisTime = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def tickStrings(self, values, scale, spacing):
        #print("*")
        if self.XAxisTime:
            #return [time.strftime("%H:%M:%S", time.localtime(max(value,0))) for value in values]
            return [str(timedelta(milliseconds=value)) for value in values]
            
        return super().tickStrings(values, scale, spacing)


class BrymenUI:
    '''
    '''
    def __init__(self):
        self.lastFileName = ''

    def ToggleXAxis(self):
        TimeAxisItem.XAxisTime = not TimeAxisItem.XAxisTime
        ##TOOD: force update in case data is invisible
        

    def UpdateValueLabels(self):
        global history

        if len(history.logSamples)>0:
            with history.dataLock:
                sample = history.logSamples[-1]
                self.labelUp.setText(sample["measureUpper"]["text"] + sample["measureUpper"]["unitOrg"])
                self.labelMain.setText(sample["measureLower"]["text"] + sample["measureLower"]["unitOrg"])

            self.labelUp.repaint()
            self.labelMain.repaint()
    

    def UpdateGraph(self):
        global history
    
        size = len(history.logSamples)

        if size>0:
            with history.dataLock:
                self.curveL.setData(x=history.logGraphData[0, :size] if TimeAxisItem.XAxisTime else None, y=history.logGraphData[2, :size])
                label = history.labels["lower"]["source"]
                unit =  history.labels["lower"]["unit"]
                self.plL.getAxis('left').setLabel(label, unit)
                self.plL.setTitle(label)

                self.curveU.setData(x=history.logGraphData[0, :size] if TimeAxisItem.XAxisTime else None, y=history.logGraphData[3, :size])
                label = history.labels["upper"]["source"]
                unit =  history.labels["upper"]["unit"]
                self.plU.getAxis('left').setLabel(label, unit)
                self.plU.setTitle(label)
       
    def PickFile(self):
        global history
        options = QFileDialog.Options()
        #options |= QFileDialog.DontUseNativeDialog
        self.lastFileName, _ = QFileDialog.getSaveFileName(None, "Save output CSV file", self.lastFileName, "All Files (*);;Comma Separated Values (*.csv)", options=options)
        #fileName = "d:/temp/aa.csv"
        try:
            history.exportCSV(self.lastFileName)
        except Exception as ex:
            msg = QtGui.QMessageBox(QtGui.QMessageBox.Critical, "Save Failed", str(ex), buttons=QtGui.QMessageBox.Ok)
            msg.exec_();
            

    def InitGraph(self, conn):
        global win
        global app
        #global history

        #create the window
        #win = pg.GraphicsWindow()
        app = QtGui.QApplication([])
        win = QtGui.QMainWindow()
        win.setWindowTitle('PyBry')

        #create the docking area
        area = DockArea()
        win.setCentralWidget(area)
        win.resize(1000,500)

        #create docks
        dDis = Dock("Display", size=(100,100))
        dSet = Dock("Settings", size=(50,1))
        dGr1 = Dock("Upper Display", size=(900,250))
        dGr2 = Dock("Main Display", size=(900,250))

        #place the docks in the area
        area.addDock(dDis, 'left')
        area.addDock(dSet, 'bottom', dDis)
        area.addDock(dGr1, 'right')
        area.addDock(dGr2, 'bottom', dGr1) #share the bottom edge of d1

        #Display Widget
        font1=QtGui.QFont("SansSerif", 16, QtGui.QFont.Bold)     
        font2=QtGui.QFont("SansSerif", 20, QtGui.QFont.Bold)     
        self.labelUp   = QtGui.QLabel("0.000V")
        self.labelMain = QtGui.QLabel("0.00000V")
        self.labelUp.setFont(font1)
        self.labelMain.setFont(font2)
        wL1 = pg.LayoutWidget()
        wL1.addWidget(self.labelUp, row=0, col=0)
        wL1.addWidget(self.labelMain, row=1, col=0)
        dDis.addWidget(wL1)
        
        #setting widgets
        wL2 = pg.LayoutWidget()
        clearBt = QtGui.QPushButton('Clear History')
        saveBt  = QtGui.QPushButton('Save to CSV')
        xAxisBt = QtGui.QPushButton('Toggle X Axis')

        portTxt = QtGui.QLineEdit(PORTNAME)
        startBt = QtGui.QPushButton('Start')
        stopBt  = QtGui.QPushButton('Stop')
        setPerBt= QtGui.QPushButton('Set Period')
        perTxt = QtGui.QLineEdit('200')

        #saveBt.setEnabled(False)

        wL2.addWidget(clearBt, row=0, col=0)
        wL2.addWidget(saveBt,row=1, col=0)
        wL2.addWidget(xAxisBt,row=2, col=0)
        wL2.addWidget(portTxt, row=3, col=0)
        wL2.addWidget(startBt,row=4, col=0)
        wL2.addWidget(stopBt,row=5, col=0)
        wL2.addWidget(setPerBt,row=6, col=0)
        wL2.addWidget(perTxt,row=6, col=1)

        clearBt.clicked.connect(history.clearSampleHistory)
        saveBt.clicked.connect(self.PickFile)
        xAxisBt.clicked.connect(self.ToggleXAxis)
        startBt.clicked.connect(lambda: conn.Start(portTxt))
        stopBt.clicked.connect(conn.Stop)
        setPerBt.clicked.connect(lambda: conn.SetPeriod(perTxt))

        dSet.addWidget(wL2)

        #graph widgets
        wgU = pg.PlotWidget(axisItems={'bottom': TimeAxisItem(orientation='bottom')})
        wgL = pg.PlotWidget(axisItems={'bottom': TimeAxisItem(orientation='bottom')})
        #wgU = pg.PlotWidget()
        #wgL = pg.PlotWidget()

        self.plU = wgU.getPlotItem()
        self.plL = wgL.getPlotItem()

        self.plU.setDownsampling(mode='mean')
        self.plU.getAxis('left').setGrid(128)
        self.plU.getAxis('left').enableAutoSIPrefix(True)
        self.plU.getAxis('bottom').setGrid(128)
        self.plU.setClipToView(True)
        self.curveU = self.plU.plot()

        self.plL.setDownsampling(mode='mean')
        self.plL.getAxis('left').setGrid(128)
        self.plL.getAxis('left').enableAutoSIPrefix(True)
        self.plL.getAxis('bottom').setGrid(128)
        self.plL.setClipToView(True)
        self.curveL = self.plL.plot()

        #link the x axis
        if LinkAxes:
            self.plL.setXLink(self.plU)
            self.plU.setXLink(slef.plL)

        #place graph widgets in the docks
        dGr1.addWidget(wgU)
        dGr2.addWidget(wgL)
        win.show()

    def Update(self):
        self.UpdateValueLabels()
        self.UpdateGraph()


if __name__ == "__main__":
    import sys
   
    conn = Connection()
    bryui = BrymenUI()

    #init graph
    bryui.InitGraph(conn)

    #setup update timer as gui updates need to done via the main thread
    timer = QtCore.QTimer()
    timer.timeout.connect(bryui.Update)
    timer.start(50)

    #run the background sampling thread 
    #conn.Start()

    #run the application
    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtGui.QApplication.instance().exec_()
