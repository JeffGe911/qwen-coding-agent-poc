// Self-checking testbench for crc8: a known-answer test ("123456789" -> 0xF4) plus seeded random
// blocks compared against a bit-serial reference model. One "ERROR:" line per mismatch and a
// TEST PASSED/FAILED verdict; it always ends with $finish (exit 0) unless the configuration is invalid.
// Plusargs: +SEED=<n> (default 1, mandatory when REQUIRE_SEED is defined), +NBLOCKS=<n> (default 4).
`timescale 1ns/1ps
module tb_crc8;
    reg        clk = 1'b0, rst_n = 1'b0, clear = 1'b0, in_valid = 1'b0;
    reg  [7:0] in_byte = 8'h00;
    wire [7:0] crc;
    integer    seed, nblocks, blk, j, len, mism;
    reg  [7:0] expect_crc;
    reg  [7:0] block [0:15];
    reg  [8*9-1:0] kat;

    crc8 dut (.clk(clk), .rst_n(rst_n), .clear(clear), .in_valid(in_valid), .in_byte(in_byte), .crc(crc));

    always #5 clk = ~clk;

    // Reference: feed the message one bit at a time, MSB first.
    function [7:0] ref_update(input [7:0] c, input [7:0] d);
        integer b;
        reg     fb;
        reg [7:0] r;
        begin
            r = c;
            for (b = 7; b >= 0; b = b - 1) begin
                fb = r[7] ^ d[b];
                r  = {r[6:0], 1'b0};
                if (fb) r = r ^ 8'h07;
            end
            ref_update = r;
        end
    endfunction

    task restart;
        begin
            @(negedge clk) clear = 1'b1;
            @(negedge clk) clear = 1'b0;
        end
    endtask

    task push(input [7:0] d);
        begin
            @(negedge clk);
            in_byte  = d;
            in_valid = 1'b1;
            @(negedge clk);
            in_valid = 1'b0;
        end
    endtask

    initial begin
        mism = 0;
        if (!$value$plusargs("SEED=%d", seed)) begin
`ifdef REQUIRE_SEED
            $fatal(1, "tb_crc8: no +SEED=<n> given; this test must be launched with an explicit seed");
`else
            seed = 1;
`endif
        end
        if (!$value$plusargs("NBLOCKS=%d", nblocks)) nblocks = 4;
        $display("tb_crc8: start seed=%0d blocks=%0d", seed, nblocks);
        repeat (2) @(posedge clk);
        rst_n = 1'b1;

        // known-answer test
        kat = "123456789";
        restart;
        expect_crc = 8'h00;
        for (j = 8; j >= 0; j = j - 1) begin
            push(kat[j*8 +: 8]);
            expect_crc = ref_update(expect_crc, kat[j*8 +: 8]);
        end
        #1;
        $display("tb_crc8: KAT crc=0x%h (reference 0x%h, published check value 0xf4)", crc, expect_crc);
        if (crc !== 8'hF4) begin
            mism = mism + 1;
            $display("ERROR: [%0t] tb_crc8 KAT mismatch: crc=0x%h expected=0xf4", $time, crc);
        end

        // seeded random blocks
        for (blk = 0; blk < nblocks; blk = blk + 1) begin
            len = 1 + ({$random(seed)} % 16);
            restart;
            expect_crc = 8'h00;
            for (j = 0; j < len; j = j + 1) begin
                block[j] = $random(seed);
                push(block[j]);
                expect_crc = ref_update(expect_crc, block[j]);
            end
            #1;
            if (crc !== expect_crc) begin
                mism = mism + 1;
                $display("ERROR: [%0t] tb_crc8 block %0d (%0d bytes): crc=0x%h expected=0x%h", $time, blk, len, crc, expect_crc);
            end
        end

        if (mism == 0) $display("TEST PASSED: tb_crc8");
        else           $display("TEST FAILED: tb_crc8 (%0d mismatches)", mism);
        $finish;
    end
endmodule
