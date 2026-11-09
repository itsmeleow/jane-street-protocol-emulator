; Address probe, not a complete I2C driver. SCL=0, SDA=1. Both output latches zero.
; TX word bits 31:24: 7-bit target address followed by write bit zero.
; RX low bit: ACK=0 or NACK=1. All high levels use release + pull-up.
SET PINS, 0
SET OE, 0
PULL
SET ISR, 0
SET X, 8
WAIT 0, 1
WAIT 1, 1
PIN OE, 1, 1 ; START: SDA falls while SCL high
DELAY 4
PIN OE, 0, 1
bits:
OUTOD 1, MSB
DELAY 4
PIN OE, 0, 0
WAIT 0, 1 ; clock stretching
DELAY 4
PIN OE, 0, 1
DELAY 4
DECJNZ bits
PIN OE, 1, 0 ; release SDA for ACK
DELAY 4
PIN OE, 0, 0
WAIT 0, 1
DELAY 4
IN 1
PIN OE, 0, 1
PIN OE, 1, 1
DELAY 4
PIN OE, 0, 0
WAIT 0, 1
DELAY 4
PIN OE, 1, 0 ; STOP: SDA rises while SCL high
PUSH
HALT
