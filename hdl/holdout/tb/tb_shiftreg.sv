// Holdout testbench for shift_reg: load pattern A, shift it out through sout while pattern B is
// shifted in through sin, then compare both. 24 pattern pairs.
// Verdict: "tb_shiftreg: all <n> patterns OK -- PASS" or "tb_shiftreg: <k> pattern(s) corrupted -- FAIL".
// NO_VERDICT leaves the verdict out (the run still ends with $finish and exit 0).
// HANG waits for a drain handshake that nothing answers; the clock keeps running, so the
// simulation never ends by itself and only the runner's wall-clock limit stops it.
`timescale 1ns/1ps
module tb_shiftreg;
    localparam W = 8;
    reg          clk = 1'b0, rst_n = 1'b0, load = 1'b0, shift_en = 1'b0, sin = 1'b0;
    reg  [W-1:0] pin = {W{1'b0}};
    wire [W-1:0] q;
    wire         sout;
    reg  [W-1:0] a, b, out_bits;
    reg          drain_done = 1'b0;
    integer      p, k, corrupted = 0, npat = 24;

    shift_reg #(.W(W)) dut (
        .clk(clk), .rst_n(rst_n), .load(load), .shift_en(shift_en), .sin(sin), .pin(pin), .q(q), .sout(sout)
    );

    always #5 clk = ~clk;

    initial begin
        $display("tb_shiftreg: start (%0d patterns)", npat);
        repeat (2) @(posedge clk);
        @(negedge clk) rst_n = 1'b1;
        for (p = 0; p < npat; p = p + 1) begin
            a = p * 37 + 5;
            b = ~(p * 11);
            @(negedge clk) begin load = 1'b1; pin = a; end
            @(negedge clk) load = 1'b0;
            for (k = W - 1; k >= 0; k = k - 1) begin
                out_bits[k] = sout;
                sin = b[k];
                shift_en = 1'b1;
                @(negedge clk);
            end
            shift_en = 1'b0;
            if (out_bits !== a || q !== b) begin
                corrupted = corrupted + 1;
                $display("tb_shiftreg: pattern %0d corrupted: out=%h (loaded %h) q=%h (shifted in %h)", p, out_bits, a, q, b);
            end
        end
`ifdef HANG
        $display("tb_shiftreg: %0d patterns shifted, waiting for drain_done from the output monitor", npat);
        $fflush;
        wait (drain_done);
`endif
`ifdef NO_VERDICT
        $display("tb_shiftreg: %0d patterns shifted through", npat);
`else
        if (corrupted == 0) $display("tb_shiftreg: all %0d patterns OK -- PASS", npat);
        else                $display("tb_shiftreg: %0d pattern(s) corrupted -- FAIL", corrupted);
`endif
        $finish;
    end
endmodule
