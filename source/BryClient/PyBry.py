import serial
import time

#Some constants
PortName            = 'Com9'
Nread               = 20
WatchdogResetPeriod = 60 #seconds
DebugOn             = False

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


def PrintResult(res):
    print("{:.6g} {} = {:.6f} {} ({}) ".format( res["value"],  res["unit"], res["valueOrg"],  res["unitOrg"],  res["source"]), end="")

def GetLitItems(pack):
    litItems = [key for key, val in pack.items() if val==True] 
    return litItems

def DecodeDigit(char):
    digit = char & 0b11111110
    if digit in segments:
        return segments[digit]
    return '?'

def DecodeValue(pack):
    res = {}

    if "Segs" not in pack:
        return None

    lit = GetLitItems(pack)

    unit = ""
    #convert to string
    s = ''.join(pack["Segs"])

    #insert decimal point    
    dotPos = None
    if "Dec1" in lit: dotPos=1
    if "Dec2" in lit: dotPos=2
    if "Dec3" in lit: dotPos=3
    if "Dec4" in lit: dotPos=4
    if dotPos!=None:
        s = s[:dotPos] + '.' + s[dotPos:]

    res["text"] = s

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
        unit = s[-1:]
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
    res["value"] = valDerived
    res["unit"] = unit
    res["valueOrg"] = valf
    res["unitOrg"] = unitOrg
    res["source"] = source
    
    return res
       
def DecodeCommon(pack):
    res = {}
    lit = GetLitItems(pack)
    res["Holding"] = "Hold" in lit
    res["Relative"]= "Delta" in lit
    res["Recording"]= "Record" in lit
    res["Crest"]= "Crest" in lit
    res["Min"]= "Min" in lit and ("Max" not in lit)
    res["Max"]= "Max" in lit and ("Min" not in lit)
    res["Avg"]= "Avg" in lit and ("Min" not in lit)

    return res
    
    
    
def Decode(inbytes):
    pack = {}
    pack["upper"] = {}
    pack["lower"] = {}

    def DecodeBit(dic, byte, bit, key):
        dic[key] = (inbytes[byte]&(1<<bit))!=0

    lower = pack["lower"]
    upper = pack["upper"]

    #Byte0
    DecodeBit(pack,  0, 0, "Auto")
    DecodeBit(pack,  0, 1, "Record")
    DecodeBit(pack,  0, 2, "Crest")
    DecodeBit(pack,  0, 3, "Hold")
    DecodeBit(lower, 0, 4, "DC")
    DecodeBit(pack,  0, 5, "Max")
    DecodeBit(pack,  0, 6, "Min")
    DecodeBit(pack,  0, 7, "Avg")

    #Byte1
    DecodeBit(lower, 1, 0, "AC")
    DecodeBit(lower, 1, 1, "T1")
    DecodeBit(lower, 1, 2, "TempDiff")
    DecodeBit(lower, 1, 3, "T2")
    DecodeBit(pack,  1, 4, "BarScale")
    DecodeBit(pack,  1, 5, "BarNeg")
    DecodeBit(lower, 1, 6, "VFD")
    DecodeBit(lower, 1, 7, "Neg")

    #Byte2
    DecodeBit(lower, 2, 0, "Delta")

    #Byte7
    DecodeBit(lower, 7, 0, "V")

    #Byte8
    DecodeBit(upper, 8, 0, "µ")
    DecodeBit(upper, 8, 1, "m")
    DecodeBit(upper, 8, 2, "A")
    DecodeBit(upper, 8, 3, "system")
    DecodeBit(upper, 8, 4, "Neg")
    DecodeBit(upper, 8, 5, "AC")
    DecodeBit(upper, 8, 6, "T2")
    DecodeBit(pack,  8, 7, "Batt")

    #Byte9
    DecodeBit(pack,  9, 0, "Cont")

    #Byte13
    DecodeBit(upper, 13, 0, "M")
    DecodeBit(upper, 13, 1, "k")
    DecodeBit(upper, 13, 2, "Hz")
    DecodeBit(upper, 13, 3, "V")
    DecodeBit(lower, 13, 4, "S")
    DecodeBit(lower, 13, 5, "F")
    DecodeBit(lower, 13, 6, "n")
    DecodeBit(lower, 13, 7, "A")

    #Byte14
    DecodeBit(lower, 14, 0, "Hz")
    DecodeBit(lower, 14, 1, "dB")
    DecodeBit(lower, 14, 2, "m")
    DecodeBit(lower, 14, 3, "µ")
    DecodeBit(lower, 14, 4, "Ohm")
    DecodeBit(lower, 14, 5, "M")
    DecodeBit(lower, 14, 6, "k")
    DecodeBit(lower, 14, 7, "Duty")

    #Decimal Points
    DecodeBit(lower, 3, 0, "Dec1")
    DecodeBit(lower, 4, 0, "Dec2")
    DecodeBit(lower, 5, 0, "Dec3")
    DecodeBit(lower, 6, 0, "Dec4")
    
    DecodeBit(upper, 10, 0, "Dec1")
    DecodeBit(upper, 11, 0, "Dec2")
    DecodeBit(upper, 12, 0, "Dec3")

    #upper segs
    upper["Segs"]=[]
    for digit in range(0, 4):
        upper["Segs"].append(DecodeDigit(inbytes[9+digit]))

    #lower segs
    lower["Segs"]=[]
    for digit in range(0, 6):
        lower["Segs"].append(DecodeDigit(inbytes[2+digit]))

    #decode upper and lower displays
    result = DecodeCommon(pack)
    result["upper"] = DecodeValue(upper)
    result["lower"] = DecodeValue(lower)
    
    #cross-display fixes
    if result["upper"]["text"]=="diod":
        result["lower"]["source"] = "Diode" + result["lower"]["source"]

    if "Temperature" in result["upper"]["source"]:
        result["upper"]["unit"] = result["lower"]["unit"]
        result["upper"]["unitOrg"] = result["lower"]["unitOrg"]

    hexs = ":".join("{:02x}".format(c) for c in inbytes)
    
    if DebugOn:
        print("{} --> {} {}".format(hexs, ''.join(lower["Segs"]), ''.join(upper["Segs"])))
    PrintResult(result["upper"])
    if DebugOn:
        print(GetLitItems(upper))
    PrintResult(result["lower"])
    if DebugOn:
        print(GetLitItems(lower))
        print(GetLitItems(pack))
 

    print("") #newline
    
def SampleLoop(ser):
    #flush the input buffer
    ser.reset_input_buffer()

    nextWatchdogReset = time.time() + WatchdogResetPeriod

    #Main loop: sample and reset watchdog
    while True:
        if ser.in_waiting >=Nread:
            inbytes = ser.read(Nread)
            Decode(inbytes)
        
        #if time to reset watchdog, do it
        if time.time() > nextWatchdogReset:
            ser.write("Go".encode())
            nextWatchdogReset = time.time() + WatchdogResetPeriod
    
def main():
    with serial.Serial('COM9') as ser:
        print(ser)
        SampleLoop(ser)

if __name__ == "__main__":
    main()
