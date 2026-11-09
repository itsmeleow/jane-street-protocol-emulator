"""Independent waveform checks plus architectural boundary tests (standard library)."""
from pathlib import Path
import unittest

from tools.assembler import AssemblyError, assemble
from tools.reference import Engine

ROOT = Path(__file__).resolve().parents[1]


def program(name):
    return assemble((ROOT / 'programs' / name).read_text())


def machine(source=None, name=None):
    e = Engine()
    e.load(program(name) if name else assemble(source))
    return e


class AssemblerTests(unittest.TestCase):
    def test_known_encoding_and_forward_label(self):
        self.assertEqual(assemble('JMP end\nSET X, 8\nend: HALT'), [0x7002, 0x1208, 0])
        self.assertEqual(assemble('OUTOD 7, MSB\nPIN OE, 3, 1'), [0xA00F, 0x201B])

    def test_reject_bad_inputs(self):
        for text in ['', 'DELAY 0', 'DELAY 4096', 'SET X, 256', 'OUT 8, LSB',
                     'WAIT 0, 2', 'JMP missing', 'HALT 1', 'x: HALT\nx: HALT',
                     'SET UNKNOWN, 1', 'NOP\n' * 65, 'JMP end\n' + 'NOP\n' * 63 + 'end:']:
            with self.subTest(text=text[:30]), self.assertRaises(AssemblyError):
                assemble(text)

    def test_examples_fit(self):
        for path in (ROOT / 'programs').glob('*.asm'):
            self.assertLessEqual(len(assemble(path.read_text())), 64)


class EngineTests(unittest.TestCase):
    def test_delay_exact_and_host_preemption(self):
        for delay in [1, 2, 15, 4095]:
            e = machine(f'SET OE, 1\nPIN PINS, 0, 1\nDELAY {delay}\nPIN PINS, 0, 0\nHALT')
            e.start()
            trace = e.run(max_ticks=delay + 10)
            self.assertEqual(sum(t.pins & 1 for t in trace), delay + 1)
        e = machine('SET OE, 255\nDELAY 4095\nHALT')
        e.start()
        e.step()
        e.step()
        e.halt()
        self.assertEqual((e.oe, e.delay_left, e.halted), (0, 0, True))

    def test_wait_and_fifo_stalls(self):
        e = machine('WAIT 2, 1\nPULL\nPUSH\nHALT')
        e.start()
        self.assertTrue(e.step(0).stalled)
        self.assertEqual(e.pc, 0)
        self.assertFalse(e.step(4).stalled)
        self.assertTrue(e.step(4).stalled)
        e.write_tx(0x12345678)
        e.step(4)
        self.assertEqual(e.osr, 0x12345678)
        e.rx.extend([1, 2, 3, 4])
        self.assertTrue(e.step(4).stalled)
        self.assertEqual(e.read_rx(), 1)
        self.assertFalse(e.step(4).stalled)
        self.assertEqual(list(e.rx), [2, 3, 4, 0])
        self.assertTrue(e.step().halted)

    def test_host_halt_all_stall_kinds(self):
        for instruction in ['WAIT 0, 1', 'PULL', 'PUSH']:
            e = machine(f'SET OE, 255\n{instruction}\nHALT')
            if instruction == 'PUSH':
                e.rx.extend([0] * 4)
            e.start()
            e.step()
            self.assertTrue(e.step().stalled)
            e.halt()
            snapshot = (e.pc, e.osr, e.isr)
            self.assertTrue(e.step().halted)
            self.assertEqual(e.oe, 0)
            self.assertEqual((e.pc, e.osr, e.isr), snapshot)

    def test_loader_reset_and_fifo_bounds(self):
        e = machine('SET OE, 255\nJMP 0')
        for i in range(4):
            e.write_tx(i)
        with self.assertRaises(BufferError):
            e.write_tx(4)
        with self.assertRaises(BufferError):
            e.read_rx()
        e.start()
        e.step()
        with self.assertRaises(RuntimeError):
            e.load([0])
        with self.assertRaises(RuntimeError):
            e.start()
        e.reset()
        self.assertEqual((e.oe, e.pc, len(e.tx), len(e.rx), e.halted), (0, 0, 0, 0, True))
        e.start()
        e.step()
        self.assertEqual(e.oe, 255)  # memory preserved

    def test_illegal_encodings_release_pins(self):
        for word in [0x0001, 0x1600, 0x2020, 0x3010, 0x4008, 0x5010,
                     0x6000, 0x7040, 0x7400, 0x8001, 0x9001, 0xA010, 0xB001, 0xFFFF]:
            e = Engine()
            e.load([0x11FF, word])
            e.start()
            e.step()
            self.assertEqual(e.oe, 255)
            trace = e.step()
            self.assertTrue(trace.error, hex(word))
            self.assertEqual((e.pc, e.oe, e.halted), (1, 0, True))
            with self.assertRaises(RuntimeError):
                e.start()

    def test_branch_counter_and_memory_boundary(self):
        e = machine('SET X, 0\nloop: DECJNZ loop\nHALT')
        e.start()
        self.assertEqual(len(e.run()), 258)  # 8-bit decrement wraps
        e = Engine()
        e.load([0xB000], 63)
        e.load([0], 0)
        e.start(63)
        e.step()
        self.assertEqual(e.pc, 0)
        self.assertTrue(e.step().halted)
        for address in [-1, 64]:
            with self.assertRaises(ValueError):
                e.load([0], address)

    def test_run_timeout(self):
        e = machine('WAIT 0, 1')
        e.start()
        with self.assertRaises(TimeoutError):
            e.run(10)


class WaveformTests(unittest.TestCase):
    def test_uart_all_bytes_and_fault(self):
        for byte in range(256):
            e = machine(name='uart_tx.asm')
            e.write_tx(byte)
            e.start()
            trace = [e.step() for _ in range(170)]
            expected_bits = [0] + [(byte >> i) & 1 for i in range(8)] + [1]
            for bit_index, expected in enumerate(expected_bits):
                segment = trace[4 + bit_index * 16:4 + (bit_index + 1) * 16]
                self.assertEqual([(t.pins & 1, t.oe & 1) for t in segment], [(expected, 1)] * 16)
            self.assertTrue(trace[-1].stalled)  # empty host FIFO, idle high
            self.assertEqual(trace[-1].pins & 1, 1)
        # A program-only edit creates a malformed stop bit; engine unchanged.
        source = (ROOT / 'programs/uart_tx.asm').read_text()
        e = machine(source.replace('PIN PINS, 0, 1', 'PIN PINS, 0, 0'))
        e.write_tx(0xFF)
        e.start()
        trace = [e.step() for _ in range(164)]
        self.assertTrue(all((t.pins & 1) == 0 for t in trace[148:164]))

    def test_spi_mode0_controller(self):
        for outgoing, incoming in [(0xA5, 0x3C), (0, 255), (255, 0)]:
            e = machine(name='spi_mode0.asm')
            e.write_tx(outgoing << 24)
            e.start()
            previous_clock, sampled, index = 0, [], 0
            for _ in range(1000):
                bit = (incoming >> (7 - min(index, 7))) & 1
                t = e.step(bit << 2)
                clock = t.pins & 1
                if clock and not previous_clock:
                    self.assertEqual(t.pins & 8, 0)  # CS asserted at sample edge
                    sampled.append((t.pins >> 1) & 1)
                if previous_clock and not clock:
                    index += 1
                previous_clock = clock
                if t.halted:
                    break
            else:
                self.fail('SPI controller timed out')
            self.assertEqual(sampled, [(outgoing >> i) & 1 for i in range(7, -1, -1)])
            self.assertEqual(e.read_rx(), incoming)
            self.assertEqual(t.pins & 9, 8)  # idle clock and CS

    def test_i2c_probe_ack_nack_and_stretch(self):
        for ack in [False, True]:
            e = machine(name='i2c_probe.asm')
            e.write_tx(0xA0 << 24)  # address 0x50, write
            e.start()
            previous, rises, falls, starts, stops = 3, 0, 0, 0, 0
            sampled, stretch_left, stretched, wait_stalls = [], 0, False, 0
            was_driving_scl = False
            for _ in range(2000):
                self.assertEqual(e.pins & 3, 0, 'open-drain outputs must remain zero')
                driving_scl = bool(e.oe & 1)
                if was_driving_scl and not driving_scl and falls == 2 and not stretched:
                    stretch_left, stretched = 9, True
                slave_low = 2 if ack and falls == 8 else 0
                if stretch_left:
                    slave_low |= 1
                    stretch_left -= 1
                bus = 3 & ~e.oe & ~slave_low
                if previous & 1 and bus & 1:
                    starts += int(bool(previous & 2) and not bus & 2)
                    stops += int(not previous & 2 and bool(bus & 2))
                if not previous & 1 and bus & 1:
                    rises += 1
                    sampled.append((bus >> 1) & 1)
                if previous & 1 and not bus & 1 and rises > falls:
                    falls += 1
                previous, was_driving_scl = bus, driving_scl
                if e.halted:
                    break
                trace = e.step(bus)
                wait_stalls += int(trace.stalled and not bus & 1)
            else:
                self.fail('I2C probe timed out')
            self.assertTrue(stretched)
            self.assertGreater(wait_stalls, 0, "stretch must actually block a WAIT")
            self.assertEqual((starts, stops), (1, 1))
            self.assertEqual(sampled[:8], [1, 0, 1, 0, 0, 0, 0, 0])
            self.assertEqual(e.read_rx(), int(not ack))

    def test_reactive_spi_command_selects_fault(self):
        for command, expected in [(0x11, 0xA5), (0x42, 0), (0xFF, 0xA5)]:
            e = machine(name='spi_reactive.asm')
            e.start()
            # Master half-period 16 ticks; CS falls after 8 idle ticks.
            bits = []
            previous_clock = 0
            for tick in range(700):
                phase = tick - 16
                active = 0 <= phase < 16 * 32
                clock = int(active and phase % 32 >= 16)
                bit_index = max(phase, 0) // 32
                mosi = (command >> (7 - min(bit_index, 7))) & 1
                inputs = clock | (mosi << 2) | (int(tick < 8 or phase >= 512) << 3)
                t = e.step(inputs)
                if active and clock and not previous_clock and bit_index >= 8:
                    self.assertEqual(t.oe & 2, 2)
                    bits.append((t.pins >> 1) & 1)
                previous_clock = clock
                if t.halted:
                    break
            else:
                self.fail('reactive target timed out')
            self.assertEqual(bits, [(expected >> i) & 1 for i in range(7, -1, -1)])
            self.assertEqual(e.read_rx(), command)
            self.assertEqual(e.oe, 0)


if __name__ == '__main__':
    unittest.main()
