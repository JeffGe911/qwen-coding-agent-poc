// Holdout testbench for crc8: six fixed frames checked against a bit-serial reference model.
// The check is an immediate assertion. By default a mismatch calls $error and the run goes on;
// with +STOP_ON_ERROR the first mismatch calls $fatal instead (vvp then exits non-zero).
// Last line: "[tb_crc8] SUMMARY: <n> frames, <bad> bad -> PASS|FAIL", then $finish.
`timescale 1ns/1ps
module tb_crc8;
    localparam NF = 6, NB = 24;
    reg        clk = 1'b0, rst_n = 1'b0, start = 1'b0, valid = 1'b0;
    reg  [7:0] data = 8'h00;
    wire [7:0] crc;
    reg  [7:0] bytes [0:NB-1];
    integer    len [0:NF-1];
    integer    f, k, off, bad = 0;
    reg  [7:0] expect_crc;
    reg        stop_on_error = 1'b0;

    crc8 dut (.clk(clk), .rst_n(rst_n), .start(start), .valid(valid), .data(data), .crc(crc));

    always #5 clk = ~clk;

    // Bit-serial reference, MSB first, polynomial 0x07.
    function [7:0] ref_crc_byte(input [7:0] c, input [7:0] d);
        integer i;
        reg [7:0] r;
        reg       fb;
        begin
            r = c;
            for (i = 7; i >= 0; i = i - 1) begin
                fb = r[7] ^ d[i];
                r  = {r[6:0], 1'b0};
                if (fb) r = r ^ 8'h07;
            end
            ref_crc_byte = r;
        end
    endfunction

    initial begin
        len[0] = 1; len[1] = 2; len[2] = 3; len[3] = 4; len[4] = 5; len[5] = 9;
        bytes[0]  = 8'h00;
        bytes[1]  = 8'h31; bytes[2]  = 8'h32;
        bytes[3]  = 8'h01; bytes[4]  = 8'h02; bytes[5]  = 8'h03;
        bytes[6]  = 8'hde; bytes[7]  = 8'had; bytes[8]  = 8'hbe; bytes[9]  = 8'hef;
        bytes[10] = 8'h48; bytes[11] = 8'h65; bytes[12] = 8'h6c; bytes[13] = 8'h6c; bytes[14] = 8'h6f;
        for (k = 0; k < 9; k = k + 1) bytes[15 + k] = 8'h31 + k;   // "123456789", check value 0xf4
    end

    initial begin
        stop_on_error = $test$plusargs("STOP_ON_ERROR");
        $display("[tb_crc8] %0d frames, stop_on_error=%0d", NF, stop_on_error);
        repeat (2) @(posedge clk);
        @(negedge clk) rst_n = 1'b1;
        off = 0;
        for (f = 0; f < NF; f = f + 1) begin
            @(negedge clk) start = 1'b1;
            @(negedge clk) start = 1'b0;
            expect_crc = 8'h00;
            for (k = 0; k < len[f]; k = k + 1) begin
                data = bytes[off + k];
                valid = 1'b1;
                expect_crc = ref_crc_byte(expect_crc, data);
                @(negedge clk);
            end
            valid = 1'b0;
            off = off + len[f];
            assert (crc === expect_crc)
            else begin
                bad = bad + 1;
                if (stop_on_error)
                    $fatal(1, "frame %0d: crc=%02h but the reference says %02h; stopping at the first CRC mismatch", f, crc, expect_crc);
                else
                    $error("frame %0d (len %0d): crc=%02h, reference %02h", f, len[f], crc, expect_crc);
            end
        end
        $display("[tb_crc8] SUMMARY: %0d frames, %0d bad -> %s", NF, bad, bad ? "FAIL" : "PASS");
        $finish;
    end
endmodule
