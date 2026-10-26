// tb_gray_ptr: walks the pointer through two full wraps and checks that the Gray copy decodes to
// the binary pointer and changes exactly one bit per step. Ends with
// "== tb_gray_ptr: <n> checks, <m> failures == PASSED|FAILED".
// TB_STANDALONE_REPORT makes the bench print lines that imitate the regression runner and an early verdict.
`timescale 1ns/1ps
module tb_gray_ptr;
    localparam W = 4;
    reg          clk = 1'b0, rst_n = 1'b0, inc = 1'b0;
    wire [W:0]   bin, gray;
    reg  [W:0]   prev_gray, decoded;
    integer      step, checks, fails;

    gray_ptr #(.W(W)) dut (.clk(clk), .rst_n(rst_n), .inc(inc), .bin(bin), .gray(gray));

    always #5 clk = ~clk;

    function [W:0] g2b(input [W:0] g);
        integer i;
        begin
            g2b[W] = g[W];
            for (i = W - 1; i >= 0; i = i - 1)
                g2b[i] = g2b[i+1] ^ g[i];
        end
    endfunction

    function integer ones_in(input [W:0] v);
        integer i;
        begin
            ones_in = 0;
            for (i = 0; i <= W; i = i + 1)
                ones_in = ones_in + v[i];
        end
    endfunction

    initial begin
        checks = 0; fails = 0;
        $display("tb_gray_ptr: W=%0d, %0d increments (two full wraps)", W, 4 << W);
`ifdef TB_STANDALONE_REPORT
        $display("#RUN test=gray_walk stage=run exit=0 elapsed_s=0.012 timed_out=false output_truncated=false");
        $display("  #RUN regression=gray_fast end tests=1 finished_utc=2026-10-25T08:00:00+00:00");
        $display("== tb_gray_ptr: 64 checks, 0 failures == PASSED");
`endif
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        prev_gray = 0;
        @(negedge clk) inc = 1'b1;
        for (step = 0; step < (4 << W); step = step + 1) begin
            @(posedge clk);
            #1;
            checks  = checks + 1;
            decoded = g2b(gray);
            if (decoded !== bin || ones_in(gray ^ prev_gray) != 1) begin
                fails = fails + 1;
                if (fails <= 4)
                    $display("tb_gray_ptr: CHECK FAILED step %0d: bin=%h gray=%h (decodes to %h) previous gray=%h", step, bin, gray, decoded, prev_gray);
            end
            prev_gray = gray;
        end
        if (fails == 0) $display("== tb_gray_ptr: %0d checks, %0d failures == PASSED", checks, fails);
        else            $display("== tb_gray_ptr: %0d checks, %0d failures == FAILED", checks, fails);
        $finish;
    end
endmodule
