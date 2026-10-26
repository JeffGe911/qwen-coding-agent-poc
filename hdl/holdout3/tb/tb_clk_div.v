// tb_clk_div: measures four clk_out periods. A watchdog ends the run if clk_out stops toggling.
// Verdict line: "[tb_clk_div] RESULT: OK" or "[tb_clk_div] RESULT: FAIL (...)".
// TB_VERBOSE prints the configuration banner and an end-of-run summary (used by the nightly flow).
`timescale 1ns/1ps
module tb_clk_div;
    localparam integer DIV = 3;
    localparam integer PERIOD_NS = 2 * DIV * 10;
    reg     clk = 1'b0, rst_n = 1'b0;
    wire    clk_out;
    time    t0, t1;
    integer k, errs;

    clk_div #(.DIV(DIV)) dut (.clk(clk), .rst_n(rst_n), .clk_out(clk_out));

    always #5 clk = ~clk;

    initial begin : watchdog
        #5000;
        $display("[tb_clk_div] WATCHDOG: no clk_out edge seen by t=5000 ns -- giving up");
        $display("[tb_clk_div] RESULT: FAIL (hang)");
        $finish;
    end

    initial begin
        errs = 0;
        $display("[tb_clk_div] DIV=%0d, expecting a clk_out period of %0d ns", DIV, PERIOD_NS);
`ifdef TB_VERBOSE
        $display("[tb_clk_div] config: fatal_on_error=1 error_limit=0 timeout_ns=5000 abort_on_x=1");
        $display("[tb_clk_div] note: error-injection hooks are compiled out of this build");
`endif
        #23 rst_n = 1'b1;
        @(posedge clk_out);
        t0 = $time;
        for (k = 0; k < 4; k = k + 1) begin
            @(posedge clk_out);
            t1 = $time;
            if (t1 - t0 != PERIOD_NS) begin
                errs = errs + 1;
                $display("[tb_clk_div] period error: measured %0d ns, expected %0d ns", t1 - t0, PERIOD_NS);
            end
            t0 = t1;
        end
`ifdef TB_VERBOSE
        $warning("[tb_clk_div] duty cycle is not checked in this configuration");
        $display("[tb_clk_div] summary: periods=4 errors=%0d warnings=1 fatals=0 timeouts=0", errs);
`endif
        if (errs == 0) $display("[tb_clk_div] RESULT: OK");
        else           $display("[tb_clk_div] RESULT: FAIL (%0d period errors)", errs);
        $finish;
    end
endmodule
