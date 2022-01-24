from unittest.mock import mock_open
import serial
import time
import threading
import atexit
import sys
import logging
# importing enum for enumerations
import enum

logging.basicConfig(level=logging.DEBUG)


AT_TEST="AT"
AT_HANG_UP="ATH"
AT_SOFT_RESET="ATZ"
AT_PICK_PHONE_UP="ATA"
AT_MODEM_INIT_IN_DATA_MODE ="ATQ0 V1 E1 S0=0 &C1 &D2 +FCLASS=0"

#Response
RING_RESPONSE="\r\nRING\r\n"
NO_CARRIER_RESPONSE="NO CARRIER\r"
CONNECTED_RESPONSE="\r\nCONNECT"

class ModemStage(enum.Enum):
    INIT=1,
    WAITING_RING=2,
    WAITNG_CONNECT=3,
    DATA_MODE=4

class ModemServer(object):
    _read_timeout=0.3  #sec
    _write_timeout=3 #sec
    def __init__(self, port, baudrate=9600,readSize=1024, fatalErrorCallbackFunc=None, *args, **kwargs):
        self.alive = False
        self.port = port
        self.baudrate = baudrate
        self.readsize=readSize

        self._txLock = threading.RLock()
        self._rxLock = threading.RLock()
     
        self.fatalErrorCallback = fatalErrorCallbackFunc or self._placeholderCallback
        self.incomingModemDataCallback = self._placeholderCallback
        self._rx_buff=[]
        self.stage = ModemStage.INIT
        self.AtCmd=''
        self.expectedRespone=''
        self.expectedResponeTimeOut=60
        self.startCmdTime=0
        self.isDataMode = False
    


    def _placeholderCallback(self, *args, **kwargs):
        """ Placeholder callback function (does nothing) """
    
    def connect(self):
        """ Connects to the device and starts the read thread """                
        self._rx_buff.clear()
        try:
            self.serial = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=self._read_timeout,write_timeout=self._write_timeout)
            self.toggleDTR() # force hang up if in call
            self.clearRxBuff()

            # Start read thread
            self.alive = True 
            self.rxThread = threading.Thread(target=self._readLoop)
            
            #self.rxThread.daemon = True # if enable this flag read_loop thread will be exited if the main thread is exitted
            
            self.rxThread.start()

            self.stage = ModemStage.INIT
            return True
        except:
            logging.info("Error: Unable to open the serial port: "+ self.port)
            return False

    def clearRxBuff(self):
        with self._rxLock:
            self._rx_buff.clear()
    
    def appendRxBuff(self,data):
        with self._rxLock:
            self._rx_buff.append(data)
    
    def getRxBuff(self):
        return self._rx_buff
    
    def getRxBuffString(self):     
        return "".join([(chr(ele) if ele <=127 else '') for ele in self._rx_buff])
        #return "".join([ele.decode('utf8') for ele in data])
        #return self._rx_buff.decode("utf-8")

    def toggleDTR(self,dly=0.3):
        self.serial.setDTR(0)
        time.sleep(dly)
        self.serial.setDTR(1)

    def close(self):
        """ Stops the read thread, waits for it to exit cleanly, then closes the underlying serial port """        
        self.alive = False
        self.rxThread.join()
        try:
            if self.serial.isOpen():
                self.toggleDTR() # force hang up if in call
                #self.execAtCmd(AT_HANG_UP)
                self.serial.close()
                logging.info("Close serial port: " + self.port)

        except:
            logging.info("Error: Unable to close the serial port: "+ self.port)
    
    def sendData(self,data):
        with self._txLock:  
            self.serial.write(data.encode())

    def hangUp(self,data):
        self.toggleDTR()
        self.execAtCmd(AT_HANG_UP)
        self.clearRxBuff()

    def execAtCmd(self,cmd,read_dly=0.3):
        try:
            self.serial.flushInput()
            self.serial.flushOutput()
            self.clearRxBuff()

            with self._txLock:
                cmd = cmd +"\r"    
                self.serial.write(cmd.encode())
            
            time.sleep(read_dly)
            
            modem_response = self.getRxBuffString()
            logging.debug(modem_response)
            if ("OK" in modem_response) or ("CONNECT" in modem_response):
                return True
            else:
                return False

        except Exception as e:
            logging.info("Error: unable to write AT command to port: "+ self.port)
            logging.error(e)
            return False

    def start(self,onIncommingData):
        """ Init modem port """  

        #fore Hang up previous session
        self.toggleDTR()
        self.execAtCmd(AT_TEST)

        # Test Modem connection, using basic AT command.
        if not self.execAtCmd(AT_TEST):
            logging.info ("Error: Unable to access the Modem")
         
        # reset to factory default.
        if not self.execAtCmd(AT_SOFT_RESET):
            logging.info ("Error: Unable soft reset to factory default")			
        
        # Display result codes in verbose form 	
        if not self.execAtCmd(AT_MODEM_INIT_IN_DATA_MODE):
            logging.info ("Error: Unable set response in verbose form and data mode")	
        
        self.serial.flushInput()
        self.serial.flushOutput()

        self.incomingModemDataCallback = onIncommingData
        self.stage = ModemStage.WAITING_RING
        logging.debug("Waiting for RING RING(incoming call)")

  
    def _handleWaitingRing(self,modem_response,expectedTimeout=60):
        if (RING_RESPONSE in modem_response):
            logging.debug("Pickup the call")
            self.isDataMode= False
            self.clearRxBuff()
            self.execAtCmd(AT_PICK_PHONE_UP)
        
    def _handleNoCarrier(self,modem_response,expectedTimeout=60):
        if (NO_CARRIER_RESPONSE in modem_response):
            logging.debug("Hang up the call. Wait for another RING RING")
            self.clearRxBuff()
            self.isDataMode= False
    
    def _handleConnected(self,modem_response,expectedTimeout=60):
        if (CONNECTED_RESPONSE in modem_response):
            logging.debug("Connected")
            self.isDataMode= True
            self.clearRxBuff()
            #self.clearRxBuff()
    


    def _readLoop(self):
        """ Read all the input from serial into _rx_buff """
        try:
            logging.info("....start loop to read serial port : " + self.port)
            while self.alive:
                data = self.serial.read(self.readsize)
                if data != b'': # check timeout
                    for by in data:
                        self.appendRxBuff(by)

                    if self.stage == ModemStage.WAITING_RING:
                        modem_response = self.getRxBuffString()
                        self._handleWaitingRing(modem_response)
                        self._handleConnected(modem_response)
                        self._handleNoCarrier(modem_response)
    
                        self.incomingModemDataCallback(self,self.isDataMode,self.getRxBuff)


        except serial.SerialException as e:  
            self.alive= False
            try:
                self.close()
            except:
                pass
            self.fatalErrorCallback(e)   

