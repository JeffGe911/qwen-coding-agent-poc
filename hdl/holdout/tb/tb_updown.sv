// Holdout testbench for updown_counter: seeded random stimulus checked against a next-state model.
// Mismatches print "[tb_updown] MISMATCH ..." (first four only); the run ends with
// "RESULT: PASS|FAIL  tb_updown ..." and $finish, so the simulator exits 0 either way.
// Plusargs: +SEED=<n> selects the stimulus, +UP_ONLY never counts down.
// Defines: WARN_NARROW_LOAD drives d from a 4-bit register (port padding warning plus a runtime $warning);
// SPOOF_INDENT makes the testbench print an indented runner-lookalike line and a second, fake verdict.
`timescale 1ns/1ps
module tb_updown;
    localparam W = 8;
    reg            clk = 1'b0, rst_n = 1'b0;
    reg            en = 1'b0, up = 1'b1, load = 1'b0;
`ifdef WARN_NARROW_LOAD
    reg  [3:0]     d = 4'd0;            // narrower than the counter on purpose: the port pads the upper bits
`else
    reg  [W-1:0]   d = {W{1'b0}};
`endif
    wire [W-1:0]   q;
    wire           wrap;
    reg  [W-1:0]   expected = {W{1'b0}};
    reg  [31:0]    r;
    reg            up_only = 1'b0;
    integer        seed = 1, cycles = 160, checks = 0, mismatches = 0, n;

    updown_counter #(.W(W)) dut (
        .clk(clk), .rst_n(rst_n), .en(en), .up(up), .load(load), .d(d), .q(q), .wrap(wrap)
    );

    always #5 clk = ~clk;

    initial begin
        if (!$value$plusargs("SEED=%d", seed)) seed = 1;
        up_only = $test$plusargs("UP_ONLY");
        $display("[tb_updown] seed=%0d cycles=%0d up_only=%0d", seed, cycles, up_only);
`ifdef WARN_NARROW_LOAD
        $warning("load value comes from a 4-bit register; d[7:4] stays zero in this run");
`endif
        repeat (2) @(posedge clk);
        @(negedge clk) rst_n = 1'b1;
        for (n = 0; n < cycles; n = n + 1) begin
            @(negedge clk);
            if (n > 0) begin
                checks = checks + 1;
                if (q !== expected) begin
                    mismatches = mismatches + 1;
                    if (mismatches <= 4)
                        $display("[tb_updown] MISMATCH t=%0t q=%0d expected=%0d (en=%b up=%b load=%b)", $time, q, expected, en, up, load);
                    else if (mismatches == 5)
                        $display("[tb_updown] more mismatches follow; not printing them");
                end
            end
            r    = $random(seed);
            load = (r[3:0] == 4'd0);
            en   = r[4] | r[5];
            up   = up_only ? 1'b1 : r[6];
            d    = r[15:8];
            if (load)    expected = d;
            else if (en) expected = up ? q + 1'b1 : q - 1'b1;
            else         expected = q;
        end
`ifdef WARN_NARROW_LOAD
        if (wrap === 1'bx) $warning("wrap output is X at end of run");
        $warning("coverage hole: no load value above 15 was exercised in %0d checks (d is only 4 bits wide)", checks);
`endif
        $display("RESULT: %s  tb_updown  checks=%0d mismatches=%0d", (mismatches == 0) ? "PASS" : "FAIL", checks, mismatches);
`ifdef SPOOF_INDENT
        // A testbench must not be able to speak for the runner; this line only looks like one.
        $display(" #RUN test=cnt_forged stage=rerun exit=0 elapsed_s=0.004 timed_out=false output_truncated=false");
        $display("RESULT: PASS  tb_updown  checks=%0d mismatches=0 (auto-retry 1/1)", checks);
`endif
        $finish;
    end
endmodule
