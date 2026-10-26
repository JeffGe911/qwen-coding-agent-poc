// Async-FIFO style pointer: W+1 bit binary pointer plus its registered Gray-code copy.
// Opt-in defects: GRAY_FAST_ENC shifts the wrong way when encoding,
// GRAY_DEBUG_TAP adds an unused, truncating debug tap that verilator -Wall reports.
`timescale 1ns/1ps
module gray_ptr #(parameter W = 4) (
    input            clk,
    input            rst_n,
    input            inc,
    output reg [W:0] bin,
    output reg [W:0] gray
);
    wire [W:0] bin_next = bin + {{W{1'b0}}, inc};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bin  <= {(W+1){1'b0}};
            gray <= {(W+1){1'b0}};
        end else begin
            bin  <= bin_next;
`ifdef GRAY_FAST_ENC
            gray <= bin_next ^ (bin_next << 1);
`else
            gray <= bin_next ^ (bin_next >> 1);
`endif
        end
    end

`ifdef GRAY_DEBUG_TAP
    wire [W-1:0] dbg_low = bin;
`endif
endmodule
