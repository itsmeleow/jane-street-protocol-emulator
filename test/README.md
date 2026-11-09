# Protocol engine RTL tests

See [RTL integration](../docs/rtl.md) for the host protocol and limits. With Icarus Verilog and `requirements.txt` installed, run from this directory:

```sh
make -B -f Makefile.engine
python -m cocotb_tools.check_results engine_results.xml
make -B
python -m cocotb_tools.check_results results.xml
```

The first compares engine execution with the Python model. The second uploads programs through actual top-level UART signals and observes protocol pins. Gate-level checks require a hardened netlist and PDK and have not yet been performed.

# Sample testbench for a Tiny Tapeout project

This is a sample testbench for a Tiny Tapeout project. It uses [cocotb](https://docs.cocotb.org/en/stable/) to drive the DUT and check the outputs.
See below to get started or for more information, check the [website](https://tinytapeout.com/hdl/testing/).

## Setting up

1. Edit [Makefile](Makefile) and modify `PROJECT_SOURCES` to point to your Verilog files.
2. Edit [tb.sv](tb.sv) and replace `tt_um_itsmeleow_protocol_emulator` with your module name.

## How to run

To run the RTL simulation:

```sh
make -B
```

To run gatelevel simulation, first harden your project and copy `../runs/wokwi/results/final/verilog/gl/{your_module_name}.v` to `gate_level_netlist.v`.

Then run:

```sh
make -B GATES=yes
```

If you wish to save the waveform in VCD format instead of FST format, edit tb.sv to use `$dumpfile("tb.svcd");` and then run:

```sh
make -B FST=
```

This will generate `tb.svcd` instead of `tb.fst`.

## How to view the waveform file

Using GTKWave

```sh
gtkwave tb.fst tb.gtkw
```

Using Surfer

```sh
surfer tb.fst
```
