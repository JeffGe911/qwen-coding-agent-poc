// CRC-8 engine (polynomial x^8+x^2+x+1 = 0x07, init 0x00, no reflection, no final xor).
// Consumes one byte per clock while in_valid is high. Written for the holdout3 triage split.
// Opt-in defects: CRC_POLY_ALT uses 0x05 as the polynomial, CRC_STREAM_IF reads a signal that does not exist.
`timescale 1ns/1ps
module crc8 (
    input            clk,
    input            rst_n,
    input            clear,
    input            in_valid,
    input      [7:0] in_byte,
    output reg [7:0] crc
);
`ifdef CRC_POLY_ALT
    localparam [7:0] POLY = 8'h05;
`else
    localparam [7:0] POLY = 8'h07;
`endif

    function [7:0] next_crc(input [7:0] c, input [7:0] d);
        integer k;
        reg [7:0] r;
        begin
            r = c ^ d;
            for (k = 0; k < 8; k = k + 1)
                r = r[7] ? ((r << 1) ^ POLY) : (r << 1);
            next_crc = r;
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            crc <= 8'h00;
        else if (clear)
            crc <= 8'h00;
        else if (in_valid)
`ifdef CRC_STREAM_IF
            crc <= next_crc(crc, in_data);
`else
            crc <= next_crc(crc, in_byte);
`endif
    end
endmodule
