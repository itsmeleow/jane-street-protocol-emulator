; Pin 0: UART TX, 8N1, LSB first, 16 engine ticks per bit.
; Whole program loops; idle high while waiting for the host FIFO.
SET PINS, 1
SET OE, 1
next_byte:
PULL
SET X, 8
PIN PINS, 0, 0
DELAY 15
bits:
OUT 0, LSB
DELAY 14
DECJNZ bits
PIN PINS, 0, 1
DELAY 15
JMP next_byte
