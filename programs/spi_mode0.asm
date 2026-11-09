; One mode-0 controller transaction. SCLK=0, MOSI=1, MISO=2, CS_n=3.
; TX FIFO word contains the byte in bits 31:24. RX low byte is sampled MSB first.
SET PINS, 8
SET OE, 11
PULL
SET ISR, 0
SET X, 8
PIN PINS, 3, 0
bits:
OUT 1, MSB
DELAY 3
PIN PINS, 0, 1
DELAY 3
IN 2
PIN PINS, 0, 0
DELAY 3
DECJNZ bits
PIN PINS, 3, 1
PUSH
HALT
