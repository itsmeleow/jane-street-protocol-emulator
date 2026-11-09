"""Cycle-by-cycle RTL comparison with the independently written PE-v0 model."""
from pathlib import Path
import random

import cocotb
from cocotb.triggers import Timer

from tools.assembler import assemble
from tools.reference import Engine

ROOT = Path(__file__).resolve().parents[1]


class Harness:
    def __init__(self, dut):
        self.dut = dut
        self.model = Engine()
        self.last_stall = False

    async def edge(self, **values):
        self.dut.clk.value = 0
        for name, value in values.items():
            getattr(self.dut, name).value = value
        await Timer(5, unit='ns')
        self.dut.clk.value = 1
        await Timer(5, unit='ns')

    async def setup(self, words):
        for name in ['clk', 'rst_n', 'soft_reset', 'tick_en', 'halt_req', 'start_req',
                     'entry', 'prog_valid', 'prog_addr', 'prog_data', 'tx_data',
                     'tx_valid', 'rx_ready', 'pins_in']:
            getattr(self.dut, name).value = 0
        await self.edge()
        await self.edge(rst_n=1)
        self.model = Engine()
        self.last_stall = False
        image = list(words) + [0] * (64 - len(words))
        for address, word in enumerate(image):
            await self.edge(prog_valid=1, prog_addr=address, prog_data=word)
        await self.edge(prog_valid=0)
        self.model.load(image)
        self.check()

    def check(self):
        e = self.model
        expected = dict(pc=e.pc, x=e.x, osr=e.osr, isr=e.isr, delay_left=e.delay_left,
                        pins_out=e.pins, pins_oe=e.oe, halted=e.halted, error=e.error,
                        tx_count=len(e.tx), rx_count=len(e.rx), stalled=self.last_stall)
        for name, value in expected.items():
            actual = int(getattr(self.dut, name).value)
            assert actual == value, f'{name}: RTL={actual:#x}, model={int(value):#x}, PC={e.pc}'
        assert int(self.dut.rx_valid.value) == (bool(e.rx) and not int(self.dut.soft_reset.value))
        assert int(self.dut.tx_ready.value) == (len(e.tx) < 4 and not int(self.dut.soft_reset.value))
        if e.rx:
            assert int(self.dut.rx_data.value) == e.rx[0]

    async def tick(self, inputs=0, tx=None, rx=False, enable=True,
                   halt=False, start=None, reset=False):
        e = self.model
        can_push = len(e.tx) < 4
        can_pop = bool(e.rx)
        # Engine and host sample old FIFO state on the same edge. No bypass.
        if reset:
            e.reset()
            self.last_stall = False
        else:
            if halt:
                e.halt()
                self.last_stall = False
            elif start is not None:
                if e.halted and not e.error:
                    e.start(start)
                    self.last_stall = False
            elif enable:
                self.last_stall = e.step(inputs).stalled
            if rx and can_pop:
                e.read_rx()
            if tx is not None and can_push:
                e.write_tx(tx)
        await self.edge(pins_in=inputs, tx_valid=int(tx is not None), tx_data=tx or 0,
                        rx_ready=int(rx), tick_en=int(enable), halt_req=int(halt),
                        start_req=int(start is not None), entry=start or 0, soft_reset=int(reset))
        self.check()


@cocotb.test()
async def isa_and_protocol_differential(dut):
    h = Harness(dut)
    rng = random.Random(0x5045)
    for path in sorted((ROOT / 'programs').glob('*.asm')):
        await h.setup(assemble(path.read_text()))
        for word in [0xA5123456, 0xFF00FF00]:
            await h.tick(tx=word, enable=False)
        await h.tick(start=0)
        for tick in range(850):
            # Reactive target gets a realistic slow serial stimulus, others get
            # changing samples to exercise WAIT/IN/OUTOD paths and FIFO stalls.
            if path.stem == 'spi_reactive':
                phase = tick - 16
                active = 0 <= phase < 512
                clock = int(active and phase % 32 >= 16)
                index = max(phase, 0) // 32
                mosi = (0x42 >> (7 - min(index, 7))) & 1
                inputs = clock | (mosi << 2) | (int(tick < 8 or phase >= 512) << 3)
            else:
                inputs = rng.randrange(256)
            await h.tick(inputs, rx=(tick % 19 == 0))
            if h.model.halted:
                break
        await h.tick(halt=True)

    # Each opcode, branch condition, shift direction, max delay, X wrap and PC wrap.
    source = '''SET X, 0
loop: DECJNZ loop
SET ISR, 0x42
SET X, 0x42
JEQ equal
SET PINS, 255
equal: JNE 0
SET OSR_HI, 0xA5
OUT 0, MSB
OUTOD 1, LSB
SET OE, 255
PIN PINS, 7, 1
PIN OE, 7, 0
IN 5
DELAY 4095
NOP
JMP 63'''
    words = assemble(source)
    words += [0] * (63 - len(words)) + [0xB000]  # NOP at 63 wraps to zero
    await h.setup(words)
    await h.tick(start=0)
    wrapped = False
    for tick in range(5300):
        await h.tick(rng.randrange(256), enable=tick % 7 != 0)
        wrapped |= h.model.pc == 63
    assert wrapped, "max delay must complete and reach PC-wrap case"
    await h.tick(halt=True)


@cocotb.test()
async def fifo_boundaries_controls_and_errors(dut):
    h = Harness(dut)
    await h.setup(assemble('PULL\nPUSH\nJMP 0'))
    await h.tick(start=0)
    # Empty TX does not bypass an enqueue on the same edge as PULL.
    await h.tick(tx=0xDEADBEEF)
    assert h.model.pc == 0
    await h.tick()
    for _ in range(4):
        await h.tick(enable=False, tx=0x11223344)
    await h.tick(enable=False, tx=0xFFFFFFFF)  # full: explicit non-handshake
    for _ in range(16):
        await h.tick()
    assert len(h.model.rx) == 4
    # Full RX does not look ahead to a simultaneous host drain.
    while h.model.pc != 1:
        await h.tick()
    await h.tick(rx=True)
    assert h.model.pc == 1
    await h.tick()
    assert h.model.pc == 2
    await h.tick(halt=True, enable=False)
    await h.tick(enable=False)  # deassert host HALT before accepting writes
    assert int(dut.prog_ready.value)
    await h.tick(reset=True, tx=9, rx=True)
    await h.tick(start=0)
    await h.tick()  # stalled PULL
    await h.tick(halt=True, enable=False)
    assert h.model.halted and h.model.oe == 0

    for blocking in ['WAIT 0, 1', 'PULL', 'DELAY 4095']:
        await h.setup(assemble(f'SET OE, 255\n{blocking}\nHALT'))
        await h.tick(start=0)
        await h.tick()
        await h.tick()
        if blocking == 'DELAY 4095':
            await h.tick(reset=True, tx=0xBAD, rx=True)  # reset during driven activity
            assert h.model.oe == 0 and h.model.halted
        else:
            await h.tick(halt=True, enable=False)
            await h.tick(reset=True)
        await h.tick(start=0)  # soft reset preserved program
        await h.tick()
        assert h.model.oe == 255

    # Writes while running are ignored, including on a tick-disabled clock.
    await h.setup(assemble('NOP\nJMP 0'))
    await h.tick(start=0)
    dut.prog_valid.value = 1
    dut.prog_addr.value = 0
    dut.prog_data.value = 0
    await h.tick(enable=False)
    dut.prog_valid.value = 0
    for _ in range(4):
        await h.tick()
    assert not h.model.halted

    invalid = [0x0001, 0x1600, 0x2020, 0x3010, 0x4008, 0x5010, 0x6000,
               0x7040, 0x7400, 0x8001, 0x9001, 0xA010, 0xB001, 0xFFFF]
    for word in invalid:
        await h.setup([0x11FF, word])
        await h.tick(start=0)
        await h.tick()
        await h.tick()
        assert h.model.error and h.model.pc == 1 and h.model.oe == 0
        await h.tick(start=0)  # sticky error rejects restart

    # Global reset invalidates memory; unwritten fetch traps (model initializes
    # memory to HALT, so this safety extension is deliberately checked separately).
    await h.edge(rst_n=0, start_req=0, tick_en=0)
    await h.edge(rst_n=1, start_req=1, entry=12)
    await h.edge(start_req=0, tick_en=1)
    assert int(dut.error.value) == 1
    assert int(dut.halted.value) == 1
    assert int(dut.pc.value) == 12
