# Programmable protocol emulator

## How it works

One PE-v0 execution engine controls eight digital pins using uploaded 16-bit instructions. Programs perform timed pin writes, shifts, samples, level waits, branches and host FIFO transfers. The engine supports command-dependent replies and intentionally malformed traffic without replacing the hardware.

Implemented examples are UART transmission, a single mode-0 SPI controller exchange, an I²C address probe with clock stretching, and a bounded reactive SPI peripheral demonstration. These are partial protocol demonstrations; complete UART RX, broader modes and transactions, robust peripheral cancellation and Ethernet remain future work.

The design contains 64 instruction words, an 8-bit scratch counter, 32-bit shift registers and four-word host FIFOs. Reset releases protocol pins and halts execution. Instructions are loaded after reset; no fixed protocol firmware is installed in silicon.

## How to test

See [RTL integration and host commands](rtl.md) for the packet format, clock assumptions, reproduction commands and verification limits. Host UART RX uses `ui_in[0]`; TX uses `uo_out[0]`. Protocol programs control `uio[7:0]`.

UART requests load one program word at a time, supply data, start/stop execution and read captured results. Default host baud is system-clock frequency divided by 174. The programmable engine tick period is independently configurable. A fixed operating frequency has not been physically validated.

## External hardware

A compatible UART host (MCU or USB-UART adapter), system clock, reset and power are required on the eventual Tiny Tapeout platform. I²C requires external pull-ups. Match signal levels to the actual board and connected target; board integration is not yet validated.

## Validation status

RTL simulation and generic synthesis have passed. No PDK-mapped area, routed timing, gate-level simulation or physical precheck results are available yet. This is an implementation in progress, not a tapeout-ready design.
