# Jane Street Protocol Emulator ASIC

A programmable peripheral impersonator for generating normal traffic and controlled faults. UART, SPI and I²C are the core targets; 10 Mbit/s Ethernet is a gated research track.

The implementation includes a **synthesizable PE-v0 engine**, writable instruction memory, bounded FIFOs, input synchronization, tick divider and UART program loader. Example programs cover UART TX, mode-0 SPI, an I²C address probe and a reactive SPI peripheral. Top-level tests upload programs through UART pins and exercise normal and deliberately corrupt responses.

## Run the architecture experiment

Python 3.10+; no third-party packages needed for these commands:

```sh
python3 -m unittest discover -s tests -v
python3 -m tools.assembler programs/uart_tx.asm -o /tmp/uart_tx.hex
python3 -m tools.reference programs/uart_tx.asm --tx 0x55 --ticks 170 > /tmp/uart_tx.csv
```

The UART program runs indefinitely and waits on an empty FIFO after sending the byte; the CLI stops at the requested trace length. Interactive input examples are exercised by the test harness.

- [RTL integration, host packet format and verification](docs/rtl.md)
- [Experimental ISA, timing contract and limitations](docs/isa-v0.md)
- [Architecture and implementation milestones](docs/target-implementation.md)
- [Instructions for repository agents](AGENTS.md)
- [RTL simulation setup](test/README.md)

The model tests check instruction boundaries/stalls, every UART byte's bit timing, a mode-0 SPI exchange, I²C ACK/NACK and clock stretching, and command-selected SPI reply corruption. They do not establish physical operating rates, complete protocol coverage, or ASIC fit.

## Tiny Tapeout

This repository uses the IHP CMOS5L Tiny Tapeout scaffold and 6×4 tile allocation. From `test`, run `make -B` for top-level loading/execution tests and `make -B -f Makefile.engine` for differential engine tests. Generic synthesis is reproducible with `yosys -Q -T -s scripts/synth.ys` from the root. PDK mapping, layout and timing closure remain outstanding. RTL simulation needs Icarus Verilog and the packages in `test/requirements.txt`; the included devcontainer supplies a development environment.

Learn more at [Tiny Tapeout](https://tinytapeout.com).
