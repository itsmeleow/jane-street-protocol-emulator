"""Tick-level PE-v0 model; input values are already synchronized, not raw GPIO."""
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import csv
import sys

from tools.assembler import assemble

MASK32 = (1 << 32) - 1


@dataclass(frozen=True)
class Trace:
    tick: int
    pc: int  # address considered at the beginning of this tick
    word: int
    inputs: int
    pins: int  # output latch after tick
    oe: int
    x: int
    osr: int
    isr: int
    stalled: bool
    halted: bool
    error: bool


class Engine:
    DEPTH = 64
    FIFO_DEPTH = 4

    def __init__(self):
        # Defined model convenience, not a proposed silicon reset of memory.
        self.memory = [0] * self.DEPTH
        self.reset()

    def reset(self):
        """Reset execution and FIFOs, preserving loaded program memory."""
        self.pc = self.pins = self.oe = self.x = self.osr = self.isr = 0
        self.tick = self.delay_left = 0
        self.halted = True
        self.error = False
        self.tx = deque()
        self.rx = deque()

    def load(self, words, address=0):
        words = list(words)
        if not self.halted:
            raise RuntimeError("program writes require halted engine")
        if not words or not 0 <= address < self.DEPTH or address + len(words) > self.DEPTH:
            raise ValueError("invalid program range")
        if any(not isinstance(w, int) or not 0 <= w <= 65535 for w in words):
            raise ValueError("instruction words must be 16-bit integers")
        self.memory[address:address + len(words)] = words

    def start(self, entry=0):
        if not self.halted or self.error:
            raise RuntimeError("start requires halted engine without error; reset clears errors")
        if not 0 <= entry < self.DEPTH:
            raise ValueError("invalid entry address")
        self.pc, self.delay_left, self.halted = entry, 0, False

    def halt(self):
        """Host halt preempts stalls and releases pins; register values are retained."""
        self.halted, self.oe, self.delay_left = True, 0, 0

    def write_tx(self, word):
        if not isinstance(word, int) or not 0 <= word <= MASK32:
            raise ValueError("TX words must be unsigned 32-bit integers")
        if len(self.tx) == self.FIFO_DEPTH:
            raise BufferError("TX FIFO full")
        self.tx.append(word)

    def read_rx(self):
        if not self.rx:
            raise BufferError("RX FIFO empty")
        return self.rx.popleft()

    def step(self, inputs=0):
        if not isinstance(inputs, int) or not 0 <= inputs <= 255:
            raise ValueError("inputs must be an 8-bit synchronized sample")
        pc = self.pc
        word = self.memory[pc]
        stalled = False
        if not self.halted:
            if self.delay_left:
                self.delay_left -= 1
                if not self.delay_left:
                    self.pc = (pc + 1) % self.DEPTH
            else:
                opcode, operand = word >> 12, word & 0xFFF
                pin, value = operand & 7, (operand >> 3) & 1
                next_pc = (pc + 1) % self.DEPTH
                valid = True
                if opcode == 0 and operand == 0:
                    self.halt()
                elif opcode == 1 and operand >> 8 <= 5:
                    target, immediate = operand >> 8, operand & 255
                    if target == 0:
                        self.pins = immediate
                    elif target == 1:
                        self.oe = immediate
                    elif target == 2:
                        self.x = immediate
                    elif target == 3:
                        self.osr = immediate
                    elif target == 4:
                        self.isr = immediate
                    else:
                        self.osr = immediate << 24
                elif opcode == 2 and operand < 32:
                    mask = 1 << pin
                    if operand & 16:
                        self.oe = (self.oe & ~mask) | (value << pin)
                    else:
                        self.pins = (self.pins & ~mask) | (value << pin)
                elif opcode in (3, 10) and operand < 16:
                    bit = ((self.osr >> 31) if value else self.osr) & 1
                    self.osr = ((self.osr << 1) & MASK32) if value else self.osr >> 1
                    mask = 1 << pin
                    if opcode == 3:
                        self.pins = (self.pins & ~mask) | (bit << pin)
                    else:
                        self.pins &= ~mask
                        self.oe = (self.oe & ~mask) | ((1 - bit) << pin)
                elif opcode == 4 and operand < 8:
                    self.isr = ((self.isr << 1) | ((inputs >> pin) & 1)) & MASK32
                elif opcode == 5 and operand < 16:
                    stalled = ((inputs >> pin) & 1) != value
                elif opcode == 6 and operand:
                    self.delay_left = operand - 1
                    if self.delay_left:
                        next_pc = pc
                elif opcode == 7 and operand >> 8 <= 3 and not operand & 0xC0:
                    condition, address = operand >> 8, operand & 63
                    if condition == 1:
                        self.x = (self.x - 1) & 255
                    taken = (condition == 0 or (condition == 1 and self.x != 0)
                             or (condition == 2 and (self.isr & 255) == self.x)
                             or (condition == 3 and (self.isr & 255) != self.x))
                    if taken:
                        next_pc = address
                elif opcode == 8 and not operand:
                    stalled = not self.tx
                    if not stalled:
                        self.osr = self.tx.popleft()
                elif opcode == 9 and not operand:
                    stalled = len(self.rx) == self.FIFO_DEPTH
                    if not stalled:
                        self.rx.append(self.isr)
                elif opcode == 11 and not operand:
                    pass
                else:
                    valid = False
                if not valid:
                    self.error = True
                    self.halt()
                    next_pc = pc
                if not stalled:
                    self.pc = next_pc
        trace = Trace(self.tick, pc, word, inputs, self.pins, self.oe, self.x,
                      self.osr, self.isr, bool(stalled), self.halted, self.error)
        self.tick += 1
        return trace

    def run(self, max_ticks=10000, inputs=None):
        """Run until HALT; inputs(tick, engine) returns the sample for that tick."""
        result = []
        for _ in range(max_ticks):
            result.append(self.step(0 if inputs is None else inputs(self.tick, self)))
            if self.halted:
                return result
        raise TimeoutError(f"engine still running after {max_ticks} ticks at PC {self.pc}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", type=Path)
    parser.add_argument("--tx", action="append", default=[], type=lambda s: int(s, 0))
    parser.add_argument("--ticks", type=int, default=1000, help="bounded trace length")
    parser.add_argument("--inputs", type=lambda s: int(s, 0), default=0)
    args = parser.parse_args()
    engine = Engine()
    engine.load(assemble(args.program.read_text()))
    for word in args.tx:
        engine.write_tx(word)
    engine.start()
    writer = csv.DictWriter(sys.stdout, fieldnames=list(Trace.__dataclass_fields__))
    writer.writeheader()
    for _ in range(args.ticks):
        trace = engine.step(args.inputs)
        writer.writerow(asdict(trace))
        if engine.halted:
            break
    if engine.error:
        parser.exit(1, "invalid instruction\n")
    if not engine.halted:
        print(f"trace limit reached at PC {engine.pc} (may be waiting for host/input)", file=sys.stderr)


if __name__ == "__main__":
    main()
