; Peripheral impersonation proof of concept, slow SPI mode 0.
; SCLK=0, MISO=1, MOSI=2, CS_n=3.
; Master sends one command byte MSB first, then clocks out one response byte.
; Command 0x42 selects intentionally corrupt response 0x00; otherwise reply 0xA5.
; Requires master half-period >=16 engine ticks and CS held low for all 16 bits.
; Samples are already synchronized: physical timing margin still unverified.
; One transaction only; early CS cancellation is not implemented.
SET OE, 0
SET ISR, 0
SET X, 8
WAIT 3, 0
command:
WAIT 0, 0
WAIT 0, 1
IN 2
DECJNZ command
SET X, 0x42
JEQ corrupt
SET OSR_HI, 0xA5
JMP reply
corrupt:
SET OSR_HI, 0
reply:
SET X, 8
WAIT 0, 0
OUT 1, MSB
PIN OE, 1, 1
WAIT 0, 1
DECJNZ more
JMP finish
more:
WAIT 0, 0
OUT 1, MSB
WAIT 0, 1
DECJNZ more
finish:
WAIT 3, 1
PUSH
HALT
