import DialModemServer
import time
import atexit
import sys

port = "/dev/ttyACM0"

modem = DialModemServer.ModemServer(port)
modem.connect()

def inCommingData(modem:DialModemServer.ModemServer,isDataMode,Databuff):
    if(isDataMode):
        data=modem.getRxBuffString()
        print(data)
        modem.sendData("Welcome to new connection")
        modem.clearRxBuff()
        


modem.start(inCommingData)

time.sleep(300)