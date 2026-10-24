// Holdout design: byte-wide CRC-8 (polynomial x^8+x^2+x+1, 0x07, init 0x00, MSB first, no reflection).
// Written for the regression-triage holdout split; defects are opt-in through defines.
module crc8 (
    input            clk,
    input            rst_n,
    input            start,   // clear the running CRC before a new frame
    input            valid,   // data holds the next frame byte
    input      [7:0] data,
    output reg [7:0] crc
);
`ifdef BUG_CRC_POLY
    localparam [7:0] POLY = 8'h05;                      // injected defect: x^1 term missing from the polynomial
`else
    localparam [7:0] POLY = 8'h07;
`endif

    function [7:0] crc8_byte(input [7:0] c, input [7:0] d);
        integer b;
        reg [7:0] x;
        begin
            x = c ^ d;
            for (b = 0; b < 8; b = b + 1)
                x = x[7] ? ((x << 1) ^ POLY) : (x << 1);
            crc8_byte = x;
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            crc <= 8'h00;
        else if (start)
            crc <= 8'h00;
        else if (valid)
`ifdef BUG_UNDECL_LINT
            crc <= crc_next;                            // injected defect: crc_next is never declared
`else
            crc <= crc8_byte(crc, data);
`endif
    end
endmodule
