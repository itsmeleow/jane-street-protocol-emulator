// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// Stop-and-wait packets: A5, command, fixed command payload. See docs/rtl.md.
module pe_host_control #(
    parameter integer UART_CLKS_PER_BIT = 174
) (
    input wire clk, input wire rst_n,
    input wire serial_rx, output wire serial_tx,
    output reg soft_reset, output reg halt_req, output reg start_req,
    output reg [5:0] entry, input wire start_ready,
    output reg prog_valid, input wire prog_ready,
    output reg [5:0] prog_addr, output reg [15:0] prog_data,
    output reg [31:0] tx_data, output reg tx_valid, input wire tx_ready,
    input wire [31:0] rx_data, input wire rx_valid, output reg rx_ready,
    input wire halted, input wire engine_error,
    output wire tick_en,
    output reg host_error
);
    localparam [2:0] SYNC = 3'd0, COMMAND = 3'd1, ARGUMENTS = 3'd2, EXECUTE = 3'd3;
    localparam integer TIMEOUT_CYCLES = UART_CLKS_PER_BIT * 32;
    localparam integer TIMEOUT_WIDTH = $clog2(TIMEOUT_CYCLES + 1);
    localparam [TIMEOUT_WIDTH-1:0] TIMEOUT_RELOAD = TIMEOUT_CYCLES - 1;
    reg [2:0] state;
    reg [7:0] command;
    reg [31:0] args;
    reg [2:0] arg_count, arg_length;
    reg [TIMEOUT_WIDTH-1:0] timeout_count;
    reg [39:0] reply;
    reg [2:0] reply_count;
    reg [15:0] tick_period, tick_count;
    wire [7:0] received;
    wire received_valid, framing_error, uart_ready;
    assign tick_en = tick_count == 16'd0;
    pe_uart #(.CLKS_PER_BIT(UART_CLKS_PER_BIT)) uart (
        .clk(clk), .rst_n(rst_n), .serial_rx(serial_rx), .serial_tx(serial_tx),
        .rx_data(received), .rx_valid(received_valid), .rx_error(framing_error),
        .tx_data(reply[7:0]), .tx_valid(reply_count != 3'd0), .tx_ready(uart_ready)
    );

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= SYNC;
            command <= 8'd0;
            args <= 32'd0;
            arg_count <= 3'd0;
            arg_length <= 3'd0;
            timeout_count <= {TIMEOUT_WIDTH{1'b0}};
            reply <= 40'd0;
            reply_count <= 3'd0;
            tick_period <= 16'd1;
            tick_count <= 16'd0;
            soft_reset <= 1'b0;
            halt_req <= 1'b0;
            start_req <= 1'b0;
            entry <= 6'd0;
            prog_valid <= 1'b0;
            prog_addr <= 6'd0;
            prog_data <= 16'd0;
            tx_data <= 32'd0;
            tx_valid <= 1'b0;
            rx_ready <= 1'b0;
            host_error <= 1'b0;
        end else begin
            soft_reset <= 1'b0;
            halt_req <= 1'b0;
            start_req <= 1'b0;
            prog_valid <= 1'b0;
            tx_valid <= 1'b0;
            rx_ready <= 1'b0;
            if (tick_count == 16'd0)
                tick_count <= tick_period - 16'd1;
            else
                tick_count <= tick_count - 16'd1;
            if (start_req || soft_reset || halt_req)
                tick_count <= 16'd0;

            if (reply_count != 3'd0 && uart_ready) begin
                reply <= {8'd0, reply[39:8]};
                reply_count <= reply_count - 3'd1;
            end

            if (framing_error) begin
                host_error <= 1'b1;
                state <= SYNC;
            end else if ((state == COMMAND || state == ARGUMENTS) &&
                         timeout_count == 0 && !received_valid) begin
                state <= SYNC;
                host_error <= 1'b1;
            end else if (state == EXECUTE) begin
                state <= SYNC;
                reply <= 40'd0; // success = 00
                reply_count <= 3'd1;
                case (command)
                    8'h01: halt_req <= 1'b1;
                    8'h02: soft_reset <= 1'b1;
                    8'h03: if (prog_ready && args[7:6] == 2'd0) begin
                        prog_addr <= args[5:0];
                        prog_data <= args[23:8];
                        prog_valid <= 1'b1;
                    end else begin
                        reply <= 40'h00000000e1;
                        host_error <= 1'b1;
                    end
                    8'h04: if (start_ready && args[7:6] == 2'd0) begin
                        entry <= args[5:0];
                        start_req <= 1'b1;
                    end else begin
                        reply <= 40'h00000000e1;
                        host_error <= 1'b1;
                    end
                    8'h05: if (tx_ready) begin
                        tx_data <= args;
                        tx_valid <= 1'b1;
                    end else begin
                        reply <= 40'h00000000e1;
                        host_error <= 1'b1;
                    end
                    8'h06: if (rx_valid) begin
                        reply <= {rx_data, 8'h00};
                        reply_count <= 3'd5;
                        rx_ready <= 1'b1;
                    end else begin
                        reply <= 40'h00000000e1;
                        host_error <= 1'b1;
                    end
                    8'h07: begin
                        reply <= {24'd0, 3'd0, host_error, rx_valid, tx_ready, engine_error, halted, 8'h00};
                        reply_count <= 3'd2;
                    end
                    8'h08: if (halted && args[15:0] != 16'd0) begin
                        tick_period <= args[15:0];
                        tick_count <= 16'd0;
                    end else begin
                        reply <= 40'h00000000e1;
                        host_error <= 1'b1;
                    end
                    default: begin
                        reply <= 40'h00000000e0;
                        host_error <= 1'b1;
                    end
                endcase
            end else if (received_valid && reply_count == 3'd0) begin
                timeout_count <= TIMEOUT_RELOAD;
                case (state)
                    SYNC: if (received == 8'ha5)
                        state <= COMMAND;
                    COMMAND: begin
                        command <= received;
                        args <= 32'd0;
                        arg_count <= 3'd0;
                        case (received)
                            8'h03: begin arg_length <= 3'd3; state <= ARGUMENTS; end
                            8'h04: begin arg_length <= 3'd1; state <= ARGUMENTS; end
                            8'h05: begin arg_length <= 3'd4; state <= ARGUMENTS; end
                            8'h08: begin arg_length <= 3'd2; state <= ARGUMENTS; end
                            default: state <= EXECUTE;
                        endcase
                    end
                    ARGUMENTS: begin
                        args[arg_count * 8 +: 8] <= received;
                        if (arg_count + 3'd1 == arg_length)
                            state <= EXECUTE;
                        else
                            arg_count <= arg_count + 3'd1;
                    end
                    default: state <= SYNC;
                endcase
            end else if (state == COMMAND || state == ARGUMENTS)
                timeout_count <= timeout_count - 1'b1;
        end
    end
endmodule
