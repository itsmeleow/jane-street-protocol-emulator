// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// Fixed host transport: 8N1. CLKS_PER_BIT must be >= 4.
module pe_uart #(
    parameter integer CLKS_PER_BIT = 174
) (
    input wire clk, input wire rst_n,
    input wire serial_rx, output wire serial_tx,
    output reg [7:0] rx_data, output reg rx_valid, output reg rx_error,
    input wire [7:0] tx_data, input wire tx_valid, output wire tx_ready
);
    localparam integer COUNT_WIDTH = $clog2(CLKS_PER_BIT + 1);
    localparam [COUNT_WIDTH-1:0] FULL_COUNT = CLKS_PER_BIT - 1;
    localparam [COUNT_WIDTH-1:0] HALF_COUNT = CLKS_PER_BIT / 2 - 1;
    localparam [2:0] IDLE = 3'd0, START = 3'd1, DATA = 3'd2,
                     STOP = 3'd3, RECOVER = 3'd4;
    (* async_reg = "true" *) reg rx_meta, rx_sync;
    reg [2:0] rx_state, rx_bit;
    reg [7:0] rx_shift;
    reg [COUNT_WIDTH-1:0] rx_count, tx_count;
    reg [9:0] tx_shift;
    reg [3:0] tx_bit;
    reg tx_busy;
    assign tx_ready = rst_n && !tx_busy;
    assign serial_tx = tx_busy ? tx_shift[0] : 1'b1;

    always @(posedge clk) begin
        if (!rst_n) begin
            rx_meta <= 1'b1;
            rx_sync <= 1'b1;
            rx_state <= IDLE;
            rx_count <= {COUNT_WIDTH{1'b0}};
            rx_bit <= 3'd0;
            rx_shift <= 8'd0;
            rx_data <= 8'd0;
            rx_valid <= 1'b0;
            rx_error <= 1'b0;
            tx_count <= {COUNT_WIDTH{1'b0}};
            tx_shift <= 10'h3ff;
            tx_bit <= 4'd0;
            tx_busy <= 1'b0;
        end else begin
            rx_meta <= serial_rx;
            rx_sync <= rx_meta;
            rx_valid <= 1'b0;
            rx_error <= 1'b0;
            case (rx_state)
                IDLE: if (!rx_sync) begin
                    rx_state <= START;
                    rx_count <= HALF_COUNT;
                end
                START: if (rx_count != 0)
                    rx_count <= rx_count - 1'b1;
                else if (rx_sync)
                    rx_state <= IDLE; // false start
                else begin
                    rx_state <= DATA;
                    rx_count <= FULL_COUNT;
                    rx_bit <= 3'd0;
                end
                DATA: if (rx_count != 0)
                    rx_count <= rx_count - 1'b1;
                else begin
                    rx_shift[rx_bit] <= rx_sync;
                    rx_count <= FULL_COUNT;
                    if (rx_bit == 3'd7)
                        rx_state <= STOP;
                    else
                        rx_bit <= rx_bit + 3'd1;
                end
                STOP: if (rx_count != 0)
                    rx_count <= rx_count - 1'b1;
                else if (rx_sync) begin
                    rx_data <= rx_shift;
                    rx_valid <= 1'b1;
                    rx_state <= IDLE;
                end else begin
                    rx_error <= 1'b1;
                    rx_state <= RECOVER;
                end
                default: if (rx_sync)
                    rx_state <= IDLE;
            endcase
            if (!tx_busy) begin
                if (tx_valid) begin
                    tx_shift <= {1'b1, tx_data, 1'b0};
                    tx_count <= FULL_COUNT;
                    tx_bit <= 4'd0;
                    tx_busy <= 1'b1;
                end
            end else if (tx_count != 0)
                tx_count <= tx_count - 1'b1;
            else begin
                tx_count <= FULL_COUNT;
                tx_shift <= {1'b1, tx_shift[9:1]};
                if (tx_bit == 4'd9)
                    tx_busy <= 1'b0;
                else
                    tx_bit <= tx_bit + 4'd1;
            end
        end
    end
endmodule
