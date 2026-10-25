// Testbench for lfsr16 (holdout2). Team C style (SystemVerilog): a reference-model scoreboard plus
// immediate assertions reported with $error. The closing "*** ... ***" banner is computed from the
// scoreboard count only (assertion messages are not counted). Always ends with $finish.
`timescale 1ns/1ps
module tb_lfsr16;
    logic        clk   = 1'b0;
    logic        rst_n = 1'b0;
    logic        en    = 1'b0;
    logic [15:0] state;
    logic        wrap;
    logic [15:0] model;
    int          fails = 0;
    int          steps;

    lfsr16 dut (.clk(clk), .rst_n(rst_n), .en(en), .state(state), .wrap(wrap));

    always #5 clk = ~clk;

    initial begin
        $display("[tb_lfsr16] seed=16'hACE1 taps=16'hB400, 1000 steps");
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        assert (state == 16'hACE1) else $error("state after reset is %h, expected ace1", state);
        model = 16'hACE1;
        en = 1'b1;
        for (steps = 0; steps < 1000; steps++) begin
            @(negedge clk);
            model = (model >> 1) ^ (model[0] ? 16'hB400 : 16'h0000);
            if (state !== model) begin
                fails++;
                if (fails <= 3) $display("[tb_lfsr16] step %0d: dut=%h model=%h", steps, state, model);
            end
            assert (!wrap) else $error("wrap high at step %0d (state=%h) before the period ended", steps, state);
        end
        if (fails == 0) $display("*** tb_lfsr16: SUCCESS (%0d steps, 0 scoreboard mismatches) ***", steps);
        else            $display("*** tb_lfsr16: FAILURE (%0d of %0d steps mismatched) ***", fails, steps);
        $finish;
    end
endmodule
