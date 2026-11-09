// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// Single-clock, four-word FIFO. No fall-through or full-cycle look-ahead.
module pe_fifo (
    input wire clk,
    input wire rst_n,
    input wire clear,
    input wire [31:0] wr_data,
    input wire wr_valid,
    output wire wr_ready,
    output wire [31:0] rd_data,
    output wire rd_valid,
    input wire rd_ready,
    output reg [2:0] count
);
    reg [31:0] storage [0:3];
    reg [1:0] wr_ptr, rd_ptr;
    wire push = wr_valid && wr_ready;
    wire pop = rd_valid && rd_ready;
    assign wr_ready = rst_n && !clear && count < 3'd4;
    assign rd_valid = rst_n && !clear && count != 3'd0;
    assign rd_data = rd_valid ? storage[rd_ptr] : 32'd0;

    always @(posedge clk) begin
        if (!rst_n || clear) begin
            wr_ptr <= 2'd0;
            rd_ptr <= 2'd0;
            count <= 3'd0;
        end else begin
            if (push) begin
                storage[wr_ptr] <= wr_data;
                wr_ptr <= wr_ptr + 2'd1;
            end
            if (pop)
                rd_ptr <= rd_ptr + 2'd1;
            case ({push, pop})
                2'b10: count <= count + 3'd1;
                2'b01: count <= count - 3'd1;
                default: begin end
            endcase
        end
    end
endmodule
