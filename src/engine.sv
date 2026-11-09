// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// PE-v0 engine: one instruction per enabled tick, combinational program read.
// Inputs are already synchronized. Control and host FIFOs use the system clock.
module pe_engine (
    input wire clk,
    input wire rst_n,
    input wire soft_reset,
    input wire tick_en,
    input wire halt_req,
    input wire start_req,
    input wire [5:0] entry,
    output wire start_ready,
    input wire prog_valid,
    output wire prog_ready,
    input wire [5:0] prog_addr,
    input wire [15:0] prog_data,
    input wire [31:0] tx_data,
    input wire tx_valid,
    output wire tx_ready,
    output wire [31:0] rx_data,
    output wire rx_valid,
    input wire rx_ready,
    input wire [7:0] pins_in,
    output reg [7:0] pins_out,
    output reg [7:0] pins_oe,
    output reg halted,
    output reg error,
    output reg stalled,
    output reg [5:0] pc,
    output reg [7:0] x,
    output reg [31:0] osr,
    output reg [31:0] isr,
    output reg [11:0] delay_left,
    output wire [2:0] tx_count,
    output wire [2:0] rx_count
);
    reg [15:0] program_mem [0:63];
    reg [63:0] written;
    wire [15:0] instruction = program_mem[pc];
    wire [3:0] opcode = instruction[15:12];
    wire [11:0] operand = instruction[11:0];
    wire [2:0] pin_index = operand[2:0];
    wire shift_bit = operand[3] ? osr[31] : osr[0];
    wire [31:0] shifted_osr = operand[3] ? {osr[30:0], 1'b0} : {1'b0, osr[31:1]};
    wire [7:0] decremented_x = x - 8'd1;
    wire [31:0] tx_head;
    wire tx_available, rx_space;
    reg tx_pop, rx_push;
    reg [7:0] next_pins, next_oe, next_x;
    reg [31:0] next_osr, next_isr;
    reg [5:0] next_pc;
    reg [11:0] next_delay;
    reg next_halted, next_error, next_stalled, valid_instruction;

    assign start_ready = rst_n && halted && !error && !soft_reset && !halt_req && !prog_valid;
    assign prog_ready = rst_n && halted && !soft_reset && !halt_req && !start_req;

    // Only validity bits reset. Program bits need no reset and survive soft reset.
    always @(posedge clk) begin
        if (!rst_n)
            written <= 64'd0;
        else if (prog_valid && prog_ready) begin
            program_mem[prog_addr] <= prog_data;
            written[prog_addr] <= 1'b1;
        end
    end

    pe_fifo tx_fifo (
        .clk(clk), .rst_n(rst_n), .clear(soft_reset),
        .wr_data(tx_data), .wr_valid(tx_valid), .wr_ready(tx_ready),
        .rd_data(tx_head), .rd_valid(tx_available), .rd_ready(tx_pop), .count(tx_count)
    );
    pe_fifo rx_fifo (
        .clk(clk), .rst_n(rst_n), .clear(soft_reset),
        .wr_data(isr), .wr_valid(rx_push), .wr_ready(rx_space),
        .rd_data(rx_data), .rd_valid(rx_valid), .rd_ready(rx_ready), .count(rx_count)
    );

    always @* begin
        next_pins = pins_out;
        next_oe = pins_oe;
        next_x = x;
        next_osr = osr;
        next_isr = isr;
        next_pc = pc;
        next_delay = delay_left;
        next_halted = halted;
        next_error = error;
        next_stalled = stalled;
        valid_instruction = 1'b1;
        tx_pop = 1'b0;
        rx_push = 1'b0;

        // Priority: reset (sequential), HALT, START, enabled engine tick.
        if (halt_req) begin
            next_halted = 1'b1;
            next_oe = 8'd0;
            next_delay = 12'd0;
            next_stalled = 1'b0;
        end else if (start_req) begin
            if (start_ready) begin
                next_halted = 1'b0;
                next_pc = entry;
                next_delay = 12'd0;
                next_stalled = 1'b0;
            end
        end else if (tick_en && !halted && !soft_reset) begin
            next_stalled = 1'b0;
            if (delay_left != 12'd0) begin
                next_delay = delay_left - 12'd1;
                if (delay_left == 12'd1)
                    next_pc = pc + 6'd1;
            end else if (!written[pc]) begin
                valid_instruction = 1'b0;
            end else begin
                next_pc = pc + 6'd1;
                case (opcode)
                    4'h0: begin
                        if (operand != 12'd0)
                            valid_instruction = 1'b0;
                        else begin
                            next_halted = 1'b1;
                            next_oe = 8'd0;
                        end
                    end
                    4'h1: begin
                        case (operand[11:8])
                            4'd0: next_pins = operand[7:0];
                            4'd1: next_oe = operand[7:0];
                            4'd2: next_x = operand[7:0];
                            4'd3: next_osr = {24'd0, operand[7:0]};
                            4'd4: next_isr = {24'd0, operand[7:0]};
                            4'd5: next_osr = {operand[7:0], 24'd0};
                            default: valid_instruction = 1'b0;
                        endcase
                    end
                    4'h2: begin
                        if (operand[11:5] != 7'd0)
                            valid_instruction = 1'b0;
                        else if (operand[4])
                            next_oe[pin_index] = operand[3];
                        else
                            next_pins[pin_index] = operand[3];
                    end
                    4'h3, 4'hA: begin
                        if (operand[11:4] != 8'd0)
                            valid_instruction = 1'b0;
                        else begin
                            next_osr = shifted_osr;
                            if (opcode == 4'h3)
                                next_pins[pin_index] = shift_bit;
                            else begin
                                next_pins[pin_index] = 1'b0;
                                next_oe[pin_index] = !shift_bit;
                            end
                        end
                    end
                    4'h4: begin
                        if (operand[11:3] != 9'd0)
                            valid_instruction = 1'b0;
                        else
                            next_isr = {isr[30:0], pins_in[pin_index]};
                    end
                    4'h5: begin
                        if (operand[11:4] != 8'd0)
                            valid_instruction = 1'b0;
                        else if (pins_in[pin_index] != operand[3]) begin
                            next_stalled = 1'b1;
                            next_pc = pc;
                        end
                    end
                    4'h6: begin
                        if (operand == 12'd0)
                            valid_instruction = 1'b0;
                        else begin
                            next_delay = operand - 12'd1;
                            if (operand != 12'd1)
                                next_pc = pc;
                        end
                    end
                    4'h7: begin
                        if (operand[7:6] != 2'd0)
                            valid_instruction = 1'b0;
                        else begin
                            case (operand[11:8])
                                4'd0: next_pc = operand[5:0];
                                4'd1: begin
                                    next_x = decremented_x;
                                    if (decremented_x != 8'd0)
                                        next_pc = operand[5:0];
                                end
                                4'd2: begin
                                    if (isr[7:0] == x)
                                        next_pc = operand[5:0];
                                end
                                4'd3: begin
                                    if (isr[7:0] != x)
                                        next_pc = operand[5:0];
                                end
                                default: valid_instruction = 1'b0;
                            endcase
                        end
                    end
                    4'h8: begin
                        if (operand != 12'd0)
                            valid_instruction = 1'b0;
                        else if (!tx_available) begin
                            next_stalled = 1'b1;
                            next_pc = pc;
                        end else begin
                            next_osr = tx_head;
                            tx_pop = 1'b1;
                        end
                    end
                    4'h9: begin
                        if (operand != 12'd0)
                            valid_instruction = 1'b0;
                        else if (!rx_space) begin
                            next_stalled = 1'b1;
                            next_pc = pc;
                        end else
                            rx_push = 1'b1;
                    end
                    4'hB: begin
                        if (operand != 12'd0)
                            valid_instruction = 1'b0;
                    end
                    default: valid_instruction = 1'b0;
                endcase
            end
            if (!valid_instruction) begin
                next_error = 1'b1;
                next_halted = 1'b1;
                next_oe = 8'd0;
                next_pc = pc;
                next_delay = 12'd0;
                tx_pop = 1'b0;
                rx_push = 1'b0;
            end
        end
    end

    always @(posedge clk) begin
        if (!rst_n || soft_reset) begin
            pins_out <= 8'd0;
            pins_oe <= 8'd0;
            x <= 8'd0;
            osr <= 32'd0;
            isr <= 32'd0;
            pc <= 6'd0;
            delay_left <= 12'd0;
            halted <= 1'b1;
            error <= 1'b0;
            stalled <= 1'b0;
        end else begin
            pins_out <= next_pins;
            pins_oe <= next_oe;
            x <= next_x;
            osr <= next_osr;
            isr <= next_isr;
            pc <= next_pc;
            delay_left <= next_delay;
            halted <= next_halted;
            error <= next_error;
            stalled <= next_stalled;
        end
    end
endmodule
