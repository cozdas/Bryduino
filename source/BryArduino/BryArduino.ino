//===========================================
// Bryduno
// Cuneyt Ozdas
//===========================================

//Some constants
const int PIN = 2;
const int POUT = 3;

const unsigned long timeoutInit     = 600L;         //ms (capacitance measurement may take ~2 seconds)
const unsigned long timeoutWatchdog = 5L * 60L * 1000L; //ms (listeners need to reset the watchdog to prevent battery drain if no one is listening)
const int           numBytesToRead  = 20;
const int           numBytesToSend  = 24;
const int           clockPeriod     = 200;          //us (you may need to adjust this depending on the signal quality)

//serial output buffer
unsigned long watchdogDeadline = 0L;
boolean       bRun = true;
unsigned long samplePeriod = 200L;  //ms
unsigned long nextSampleTime = 0L; //ms

String clientCmd = "";

union Data
{
  unsigned char outbytes[numBytesToSend];
  struct
  {
    unsigned char inbytes[numBytesToRead];
    unsigned long sampleTime;
  };
};

Data data;

void ResetWatchdog()
{
  watchdogDeadline = millis() + timeoutWatchdog;
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
  digitalWrite(POUT, HIGH);
  delay(10);
  digitalWrite(POUT, LOW);
}

boolean InitSequence()
{
  //wait for the existing transmission to end
  while (digitalRead(PIN) == LOW)
    delay(clockPeriod * numBytesToRead * 8L / 1000);

  //send the 10ms pulse
  SendRequestPulse();

  //wait until we receive response
  unsigned long deadline = millis() + timeoutInit;
  while (digitalRead(PIN) == HIGH)
  {
    if (millis() > deadline)
    {
      deadline = millis() + timeoutInit;

      //double check before sending a new init pulse as it can be taken as a clock
      if (digitalRead(PIN) == HIGH)
        SendRequestPulse();
    }
  }

  return (digitalRead(PIN) == LOW);
}

//read the packet from Brymen and fill the output buffer
boolean ReadBytes()
{
  //start the clock
  for (int i = 0; i < numBytesToRead; ++i)
  {
    unsigned char bVal = 0;
    for (int j = 0; j < 8; ++j)
    {
      //setup edge
      digitalWrite(POUT, HIGH);
      delayMicroseconds(clockPeriod >> 1);

      //read
      if (digitalRead(PIN))
        bVal |= 1 << j;

      //sample edge
      digitalWrite(POUT, LOW);
      delayMicroseconds(clockPeriod >> 1);
    }
    data.inbytes[i] = bVal;
  }
}

void ExecuteCmd(String cmd)
{
  if (cmd == "")
    return;

  else if(cmd=="[Rst]")
  {
    bRun = true;
    ResetWatchdog();
  }
  else if (cmd == "[Go]")
  {
    bRun = true;
    nextSampleTime = 0L;
    ResetWatchdog();
  }
  else if (cmd == "[Stop]")
  {
    bRun = false;
  }
  else if (cmd.startsWith("[Per="))
  {
    int numberStart = cmd.indexOf('=') + 1;
    int numberEnd = cmd.indexOf(']');
    unsigned long per = cmd.substring(numberStart, numberEnd).toInt();
    samplePeriod = per;
    nextSampleTime = 0L;
    return;
  }
}

void loop()
{
  //if enabled run the sampling
  if (bRun == true)
  {
    //wait for the next sample time
    while(millis()<nextSampleTime)
    {
      delay(1);
    }
    nextSampleTime = millis() + samplePeriod;  //TODO: this will fail in case of overflow which happens in ~49 days after boot

    //init sequence
    boolean res = InitSequence();
    if (res)
    {
      data.sampleTime = millis();
      ReadBytes();

      Serial.write(data.outbytes, numBytesToSend);
    }
  }

  //check if we have request from the client
  while (Serial.available())
  {
    char inChar = (char)Serial.read();
    if(inChar=='[')
      clientCmd="";
    clientCmd += inChar;
    if(inChar==']')
      ExecuteCmd(clientCmd);
  }

  

  //check watchdog. Stop if no one has been listening.
  if (millis() > watchdogDeadline)
    bRun = false;
}
