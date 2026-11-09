# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests: upload through UART pins, execute, inspect actual GPIO."""
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, ReadOnly, Timer, with_timeout

from tools.assembler import assemble

ROOT = Path(__file__).resolve().parents[1]
CLK_NS = 10


class Host:
    def __init__(self, dut):
        self.dut = dut
        self.bit_cycles = int(dut.UART_BIT_CYCLES.value)
        self.bit_ns = self.bit_cycles * CLK_NS

    async def send_byte(self, byte, bad_stop=False):
        await FallingEdge(self.dut.clk)
        for bit in [0] + [(byte >> i) & 1 for i in range(8)] + [int(not bad_stop)]:
            self.dut.ui_in.value = bit
            await Timer(self.bit_ns, unit='ns')
        self.dut.ui_in.value = 1

    async def receive_byte(self):
        await with_timeout(FallingEdge(self.dut.host_tx), self.bit_ns * 200, 'ns')
        await Timer(self.bit_ns * 3 // 2, unit='ns')
        value = 0
        for i in range(8):
            value |= (int(self.dut.uo_out.value) & 1) << i
            await Timer(self.bit_ns, unit='ns')
        assert int(self.dut.uo_out.value) & 1, 'host UART missing stop bit'
        return value

    async def receive(self, length):
        return bytes([await self.receive_byte() for _ in range(length)])

    async def command(self, command, payload=b'', response_length=1):
        response = cocotb.start_soon(self.receive(response_length))
        for byte in bytes([0xA5, command]) + payload:
            await self.send_byte(byte)
        result = await response
        # End of response stop bit; obey stop-and-wait transport contract.
        await Timer(self.bit_ns, unit='ns')
        return result

    async def upload(self, name):
        words = assemble((ROOT / 'programs' / name).read_text())
        for address, word in enumerate(words):
            assert await self.command(3, bytes([address, word & 255, word >> 8])) == b'\0'


async def setup(dut):
    dut.ena.value = 1
    dut.rst_n.value = 0
    dut.ui_in.value = 1
    dut.uio_in.value = 0
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit='ns').start())
    await ClockCycles(dut.clk, 5)
    await FallingEdge(dut.clk)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    return Host(dut)


@cocotb.test()
async def upload_uart_and_decode_pin(dut):
    host = await setup(dut)
    assert int(dut.uio_oe.value) == 0
    assert await host.command(7, response_length=2) == b'\x00\x05'  # halted, TX space
    assert await host.command(0xFF) == b'\xe0'
    assert await host.command(3, b'\x40\x00\x00') == b'\xe1'  # address bounds
    assert await host.command(8, b'\x00\x00') == b'\xe1'  # zero tick period
    await host.upload('uart_tx.asm')
    for i in range(4):
        assert await host.command(5, bytes([i, 0, 0, 0])) == b'\0'
    assert await host.command(5, b'\xff\0\0\0') == b'\xe1'  # full FIFO
    assert await host.command(2) == b'\0'  # clear queues, preserve program
    assert await host.command(5, b'\x55\0\0\0') == b'\0'

    waveform = []
    async def monitor():
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            waveform.append((int(dut.uio_out.value) & 1, int(dut.uio_oe.value) & 1))
    watcher = cocotb.start_soon(monitor())
    assert await host.command(4, b'\0') == b'\0'
    await ClockCycles(dut.clk, 180)
    watcher.cancel()
    start = next(i for i, (value, oe) in enumerate(waveform) if oe and not value)
    for index, bit in enumerate([0] + [(0x55 >> i) & 1 for i in range(8)] + [1]):
        assert waveform[start + index * 16:start + (index + 1) * 16] == [(bit, 1)] * 16
    assert await host.command(3, b'\0\0\0') == b'\xe1'  # running write rejected
    assert await host.command(8, b'\x02\x00') == b'\xe1'  # running divider rejected
    assert await host.command(1) == b'\0'  # host halt escapes blocked PULL
    assert int(dut.uio_oe.value) == 0
    assert await host.command(8, b'\x03\x00') == b'\0'
    assert await host.command(2) == b'\0'
    assert await host.command(4, b'\x3f') == b'\0'  # unwritten fetch traps
    status = await host.command(7, response_length=2)
    assert status[1] & 3 == 3
    assert await host.command(4, b'\0') == b'\xe1'  # sticky engine error
    assert await host.command(2) == b'\0'
    assert await host.command(4, b'\0') == b'\0'  # program survived reset
    assert await host.command(1) == b'\0'


@cocotb.test()
async def reactive_spi_via_uploaded_program(dut):
    host = await setup(dut)
    await host.upload('spi_reactive.asm')
    for command, expected in [(0x11, 0xA5), (0x42, 0x00)]:
        assert await host.command(2) == b'\0'
        dut.uio_in.value = 8  # CS_n high; clock low
        assert await host.command(4, b'\0') == b'\0'
        await FallingEdge(dut.clk)
        dut.uio_in.value = 0
        for i in range(7, -1, -1):
            data = ((command >> i) & 1) << 2
            dut.uio_in.value = data
            await ClockCycles(dut.clk, 32)
            await FallingEdge(dut.clk)
            dut.uio_in.value = data | 1
            await ClockCycles(dut.clk, 32)
            await FallingEdge(dut.clk)
            dut.uio_in.value = data
        response = 0
        for _ in range(8):
            await ClockCycles(dut.clk, 32)
            await FallingEdge(dut.clk)
            assert int(dut.uio_oe.value) & 2
            response = (response << 1) | ((int(dut.uio_out.value) >> 1) & 1)
            dut.uio_in.value = 1
            await ClockCycles(dut.clk, 32)
            await FallingEdge(dut.clk)
            dut.uio_in.value = 0
        dut.uio_in.value = 8
        await ClockCycles(dut.clk, 16)
        assert response == expected
        assert int(dut.uio_oe.value) == 0
        packet = await host.command(6, response_length=5)
        assert packet == bytes([0, command, 0, 0, 0])
        assert await host.command(6) == b'\xe1'  # empty RX reports error


@cocotb.test()
async def host_parser_resynchronizes(dut):
    host = await setup(dut)
    # Incomplete WRITE packet times out without changing program memory.
    for byte in [0xA5, 3, 0]:
        await host.send_byte(byte)
    await Timer(host.bit_ns * 40, unit='ns')
    assert (await host.command(7, response_length=2))[1] & 0x10
    # Corrupt UART stop bit discards pending packet, then recovery accepts SYNC.
    await host.send_byte(0xA5)
    await host.send_byte(3, bad_stop=True)
    await Timer(host.bit_ns * 3, unit='ns')
    assert await host.command(1) == b'\0'
    assert await host.command(7, response_length=2) == b'\x00\x15'
