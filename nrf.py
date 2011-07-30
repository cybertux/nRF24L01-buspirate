import serial
import time

class BP_SPI(object):
	def __init__(self, port):
		self.serial = serial.Serial(port, 115200, timeout=0.1)
		self.serial.write('\x00\x0f')
		self.serial.flush()
		time.sleep(0.1)
		self.serial.write('\r\n'*10 + '#')
		time.sleep(0.1)
		self.serial.write('\0'*20 + chr(0x01))
		self.serial.flush()
		time.sleep(0.1)
		
		i = self.serial.read(self.serial.inWaiting())
		if not i.endswith("SPI1"):
			raise IOError("Could not initialize BusPirate")
			
		self._power = False
		self._pullup = False
		self._aux = False
		self._cs = False
	
	def setCS(self, val):
		self.serial.write(chr(0x02 | bool(val)))
		assert(self.serial.read(1) == chr(1))
		self._cs = val
		
	def transfer(self, data='', size=0):
		size = max(len(data), size)
		data += (size - len(data)) * '\0'
		self.serial.write(chr(0x10|(size-1))+data)
		self.serial.flush()
		d = self.serial.read(size+1)
		assert(d[0] == chr(1))
		return d[1:]
		
	def cs_transfer(self, data='', size=0):
		size = max(len(data), size)
		data += (size - len(data)) * '\0'
		self.serial.write(chr(0x02)+chr(0x10|(size-1))+data+chr(0x03))
		self.serial.flush()
		d = self.serial.read(size+3)
		assert (d[0] == chr(1) and d[1] == chr(1) and d[-1] == chr(1))
		return d[2:-1]
		
	def set_outputs(self, power=None, pullup=None, aux=None, cs=None):
		if power is None:  power = self._power
		if pullup is None: pullup = self._pullup
		if aux is None:	aux = self._aux
		if cs is None:	 cs = self._cs 
		self.serial.write(chr(0x40
			  | (bool(power) << 3)
			  | (bool(pullup) << 2)
			  | (bool(aux) << 1)
			  | bool(cs)))
		assert(self.serial.read(1) == chr(1))
		self._power, self._pullup, self._aux, self._cs = power, pullup, aux, cs
		
	def set_mode(self, power, ckp, cke, smp):
		self.serial.write(chr(0x80
			  | (bool(power) << 3)
			  | (bool(ckp) << 2)
			  | (bool(cke) << 1)
			  | bool(smp)))
		assert(self.serial.read(1) == chr(1))

# Registers
CONFIG = 0x00
EN_AA = 0x01
EN_RXADDR = 0x02
SETUP_AW = 0x03
SETUP_RETR = 0x04
RF_CH = 0x05
RF_SETUP = 0x06
STATUS = 0x07
OBSERVE_TX = 0x08
CD = 0x09
RX_ADDR_P0 = 0x0A
RX_ADDR_P1 = 0x0B
RX_ADDR_P2 = 0x0C
RX_ADDR_P3 = 0x0D
RX_ADDR_P4 = 0x0E
RX_ADDR_P5 = 0x0F
TX_ADDR = 0x10
RX_PW_P0 = 0x11
RX_PW_P1 = 0x12
RX_PW_P2 = 0x13
RX_PW_P3 = 0x14
RX_PW_P4 = 0x15
RX_PW_P5 = 0x16
FIFO_STATUS = 0x17

# Bit Mnemonics
MASK_RX_DR = 6
MASK_TX_DS = 5
MASK_MAX_RT = 4
EN_CRC = 3
CRCO = 2
PWR_UP = 1
PRIM_RX = 0
ENAA_P5 = 5
ENAA_P4 = 4
ENAA_P3 = 3
ENAA_P2 = 2
ENAA_P1 = 1
ENAA_P0 = 0
ERX_P5 = 5
ERX_P4 = 4
ERX_P3 = 3
ERX_P2 = 2
ERX_P1 = 1
ERX_P0 = 0
AW = 0
ARD = 4
ARC = 0
PLL_LOCK = 4
RF_DR = 3
RF_PWR = 1
LNA_HCURR = 0
RX_DR = 6
TX_DS = 5
MAX_RT = 4
RX_P_NO = 1
TX_FULL = 0
PLOS_CNT = 4
ARC_CNT = 0
TX_REUSE = 6
FIFO_FULL = 5
TX_EMPTY = 4
RX_FULL = 1
RX_EMPTY = 0

# Instruction Mnemonics 
R_REGISTER = 0x00
W_REGISTER = 0x20
REGISTER_MASK = 0x1F
R_RX_PAYLOAD = 0x61
W_TX_PAYLOAD = 0xA0
FLUSH_TX = 0xE1
FLUSH_RX = 0xE2
REUSE_TX_PL = 0xE3
NOP = 0xFF


mirf_ADDR_LEN = 5
mirf_CONFIG = ((1<<EN_CRC) | (0<<CRCO) )

		
class BP_nRF(BP_SPI):
	#csn = cs, ce = AUX
	def __init__(self, port, payload_size=15, channel=23):
		super(BP_nRF, self).__init__(port)
		self.set_mode(power=1, ckp=0, cke=1, smp=0)
		self.set_outputs(cs=True, aux=False)
		self.payload_size = payload_size
		self.channel = channel
		self.PTX = False
	
	def config(self):	
		# Set RF channel
		self.configRegister(RF_CH, self.channel)

		# Set length of incoming payload 
		self.configRegister(RX_PW_P0, self.payload_size)
		self.configRegister(RX_PW_P1, self.payload_size)

		#Start receiver 
		self.powerUpRx()
		self.flushRx()
		
	def setRADDR(self, adr):
		self.set_outputs(aux=False)
		self.writeRegister(RX_ADDR_P1, adr)
		self.set_outputs(aux=True)
		
	def setTADDR(self, adr):
		self.writeRegister(RX_ADDR_P0, adr)
		self.writeRegister(TX_ADDR, adr)
	
	def dataReady(self): 
		status = self.getStatus()

		if status & (1 << RX_DR):
			return 1
		else:
			return not self.rxFifoEmpty()

	def rxFifoEmpty(self):
		fifoStatus = ord(self.readRegister(FIFO_STATUS))
		return (fifoStatus & (1 << RX_EMPTY))
	
	def getData(self) :
		data = self.cs_transfer(chr(R_RX_PAYLOAD), size=self.payload_size+1)
		self.configRegister(STATUS,(1<<RX_DR))
		return data[1:]

	def configRegister(self, reg, value):
		self.cs_transfer(chr(W_REGISTER | (REGISTER_MASK & reg)) + chr(value))

	def readRegister(self, reg, size=1):
		return self.cs_transfer(chr(R_REGISTER | (REGISTER_MASK & reg)), size=size+1)[1:]
	
	def writeRegister(self, reg, data):
		self.cs_transfer(chr(W_REGISTER | (REGISTER_MASK & reg))+data)

	def send(self, data):
		while self.PTX:
			status = self.getStatus()
			
			print 'send status', bin(status)
			
			if status & ((1 << TX_DS)  | (1 << MAX_RT)):
				self.PTX = 0
				break
			
		self.set_outputs(aux=False)
		self.powerUpTx()
		self.cs_transfer(chr(FLUSH_TX))
		self.cs_transfer(chr(W_TX_PAYLOAD) + data, size=self.payload_size+1)
		self.set_outputs(aux=True)
			

	def isSending(self):
		if self.PTX:
			status = self.getStatus()
			if status & ((1 << TX_DS)  | (1 << MAX_RT)):
				self.powerUpRx()
				return False
			else:
				return True
		else:
			return False
			

	def getStatus(self):
		return ord(self.readRegister(STATUS))
		
	def powerUpRx(self):
		self.PTX = 0
		self.set_outputs(aux=0)
		self.configRegister(CONFIG, mirf_CONFIG | ( (1<<PWR_UP) | (1<<PRIM_RX) ) )
		self.set_outputs(aux=1)
		self.configRegister(STATUS,(1 << TX_DS) | (1 << MAX_RT))

	def flushRx(self):
		self.cs_transfer(chr(FLUSH_RX))
	
	def powerUpTx(self):
		self.PTX = 1
		self.configRegister(CONFIG, mirf_CONFIG | ( (1<<PWR_UP) | (0<<PRIM_RX) ))


	def powerDown(self):
		self.set_outputs(aux=0)
		self.configRegister(CONFIG, mirf_CONFIG)	
	
		
		
if __name__ == '__main__':
	bp = BP_nRF('/dev/ttyUSB1')

	bp.set_outputs(power=True)
	
	time.sleep(0.1)
	
	bp.setRADDR('clie1')
	bp.config()
	
	print 'status', bin(bp.getStatus())
	
	c = 0
	
	while 1:
		bp.setTADDR('serv1')
		bp.send(str(c)+"test!")
	
		print c, bin(bp.getStatus()), bp.isSending()
		
		if bp.dataReady():
			print 'received', bp.getData()
		
		c = (c+1)%100
		
		time.sleep(1)
		
	
	print 'status', bin(bp.getStatus())
	
	time.sleep(0.1)
	
	bp.set_outputs(power=False)
	