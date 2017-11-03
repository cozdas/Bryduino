//===========================================
// Bryduno
// Cuneyt Ozdas
//===========================================

//Some constants
const int PIN =2;
const int POUT=3;

const unsigned long timeoutInit     = 2100L;        //ms (capacitance measurement may take ~2 seconds)
const unsigned long timeoutWatchdog = 5L*60L*1000L; //ms (listeners need to reset the watchdog to prevent battery drain if no one is listening)
const int           numBytesToRead  = 20;
const int           clockPeriod     = 200;          //us (you may need to adjust this depending on the signal quality)

//serial output buffer
unsigned char outBuffer[numBytesToRead];
unsigned long watchdogDeadline = 0L;
boolean       bRun = true;

void ResetWatchdog()
{
  watchdogDeadline = millis()+timeoutWatchdog;  
}

void setup() 
{
  pinMode(PIN, INPUT);
  pinMode(POUT, OUTPUT);

  digitalWrite(PIN, HIGH);
  Serial.begin(9600);

  bRun = true;
  ResetWatchdog();
}

//sends 10ms low pulse
void SendRequestPulse()
{
  digitalWrite(POUT, LOW);
  delay(10);
  digitalWrite(POUT, HIGH);
}

boolean InitSequence()
{
  //wait for the existing transmission to end
  while(digitalRead(PIN)==LOW)
    delay(clockPeriod*numBytesToRead*8L/1000);

  //send the 10ms pulse
  SendRequestPulse();

  //wait until we receive response
  unsigned long deadline = millis() + timeoutInit;
  while(digitalRead(PIN)==HIGH)
  {
    if(millis()>deadline)
    {
      SendRequestPulse();
      deadline = millis()+ timeoutInit;
    }
  }

  return (digitalRead(PIN)==LOW);
}

//read the packet from Brymen and fill the output buffer
boolean ReadBytes()
{
  //start the clock
  for(int i=0; i<numBytesToRead; ++i)
  {
    unsigned char bVal = 0;
    for(int j=0; j<8; ++j)
    {
      //setup edge
      digitalWrite(POUT, LOW);
      delayMicroseconds(clockPeriod>>1);

      //read
      if(digitalRead(PIN))
        bVal |= 1<<j;

      //sample edge
      digitalWrite(POUT, HIGH);
      delayMicroseconds(clockPeriod>>1);
    }
    outBuffer[i]=bVal;
  }  
}

void ExecuteCmd(String cmd)
{
  if(cmd=="") return;
  
  if(cmd=="Go")
  {
    bRun = true;
    ResetWatchdog();
    return;
  }

  if(cmd == "Stop")
  {
    bRun = false;
    return;
  }
}

void loop() 
{
  //if enabled run the sampling
  if(bRun==true)
  {
    //init sequence
    boolean res = InitSequence();
    if(res)
    {
      ReadBytes();
      Serial.write(outBuffer, numBytesToRead);
    }
  }

  //check if we have request from the client
  String clientCmd = "";
  while (Serial.available()) 
  {
    char inChar = (char)Serial.read();
    clientCmd += inChar;
  }

  ExecuteCmd(clientCmd);

  //check watchdog. Stop if no one has been listening.
  if(millis()>watchdogDeadline)
    bRun = false;
 
  delay(50);
}
