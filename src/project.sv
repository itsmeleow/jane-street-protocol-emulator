/*
 * Copyright (c) 2026 Leo Wang
 * SPDX-License-Identifier: Apache-2.0
 */
`default_nettype none

module tt_um_itsmeleow_protocol_emulator #(
    parameter integer UART_CLKS_PER_BIT = 174
) (
    input wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input wire ena,
    input wire clk,
    input wire rst_n
);
    wire active_rst_n = rst_n && ena;
    (* async_reg = "true" *) reg [7:0] pins_meta, pins_sync;
    wire soft_reset, halt_req, start_req, start_ready, prog_valid, prog_ready;
    wire tx_valid, tx_ready, rx_valid, rx_ready, halted, engine_error, tick_en;
    wire [5:0] entry, prog_addr;
    wire [15:0] prog_data;
    wire [31:0] tx_data, rx_data;
    wire [7:0] pins_out, pins_oe;
    wire host_tx, host_error;
    wire stalled;
    wire [5:0] pc;
    wire [7:0] x;
    wire [31:0] osr, isr;
    wire [11:0] delay_left;
    wire [2:0] tx_count, rx_count;

    always @(posedge clk) begin
        if (!active_rst_n) begin
            pins_meta <= 8'd0;
            pins_sync <= 8'd0;
        end else begin
            pins_meta <= uio_in;
            pins_sync <= pins_meta;
        end
    end
    pe_host_control #(.UART_CLKS_PER_BIT(UART_CLKS_PER_BIT)) host (
        .clk(clk), .rst_n(active_rst_n), .serial_rx(ui_in[0]), .serial_tx(host_tx),
        .soft_reset(soft_reset), .halt_req(halt_req), .start_req(start_req),
        .entry(entry), .start_ready(start_ready), .prog_valid(prog_valid),
        .prog_ready(prog_ready), .prog_addr(prog_addr), .prog_data(prog_data),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready),
        .rx_data(rx_data), .rx_valid(rx_valid), .rx_ready(rx_ready),
        .halted(halted), .engine_error(engine_error), .tick_en(tick_en), .host_error(host_error)
    );
    pe_engine engine (
        .clk(clk), .rst_n(active_rst_n), .soft_reset(soft_reset), .tick_en(tick_en),
        .halt_req(halt_req), .start_req(start_req), .entry(entry), .start_ready(start_ready),
        .prog_valid(prog_valid), .prog_ready(prog_ready), .prog_addr(prog_addr), .prog_data(prog_data),
        .tx_data(tx_data), .tx_valid(tx_valid), .tx_ready(tx_ready),
        .rx_data(rx_data), .rx_valid(rx_valid), .rx_ready(rx_ready),
        .pins_in(pins_sync), .pins_out(pins_out), .pins_oe(pins_oe),
        .halted(halted), .error(engine_error), .stalled(stalled),
        .pc(pc), .x(x), .osr(osr), .isr(isr), .delay_left(delay_left),
        .tx_count(tx_count), .rx_count(rx_count)
    );
    assign uo_out = {7'd0, host_tx};
    assign uio_out = pins_out;
    // Immediate external release on deselect/reset; state reset is synchronous.
    assign uio_oe = active_rst_n ? pins_oe : 8'd0;
    wire _unused = &{ui_in[7:1], host_error, stalled, pc, x, osr, isr,
                    delay_left, tx_count, rx_count, 1'b0};
endmodule
