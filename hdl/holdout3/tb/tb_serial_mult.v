// tb_serial_mult: exhaustive 4x4 check of serial_mult. There is deliberately no watchdog;
// this team relies on the regression's wall-clock limit. Verdict: "mult: ALL TESTS PASSED (...)"
// or "mult: TESTS FAILED, ...". TB_LEGACY_SUMMARY is the old summary-only build (prints a count, no verdict).
// MULT_REV_A uses the port name of a previous multiplier revision.
`timescale 1ns/1ps
module tb_serial_mult;
    reg        clk = 1'b0, rst_n = 1'b0, start = 1'b0;
    reg  [3:0] x = 4'd0, y = 4'd0;
    wire [7:0] p;
    wire       done;
    integer    i, j, bad, ran;

`ifdef MULT_REV_A
    serial_mult dut (.clk(clk), .rst_n(rst_n), .go(start), .x(x), .y(y), .p(p), .done(done));
`else
    serial_mult dut (.clk(clk), .rst_n(rst_n), .start(start), .x(x), .y(y), .p(p), .done(done));
`endif

    always #5 clk = ~clk;

    initial begin
        bad = 0; ran = 0;
        $display("mult: exhaustive 4x4 check (256 products)");
        #12 rst_n = 1'b1;
        for (i = 0; i < 16; i = i + 1) begin
            for (j = 0; j < 16; j = j + 1) begin
                @(negedge clk);
                x = i; y = j; start = 1'b1;
                @(negedge clk);
                start = 1'b0;
                @(posedge done);
                #1;
                ran = ran + 1;
                if (p !== i * j) begin
                    bad = bad + 1;
                    if (bad <= 3) $display("mult: WRONG %0d x %0d = %0d (expected %0d)", i, j, p, i * j);
                end
            end
        end
`ifdef TB_LEGACY_SUMMARY
        $display("mult: %0d products computed; comparison table written by the post-processing step", ran);
`else
        if (bad == 0) $display("mult: ALL TESTS PASSED (%0d products)", ran);
        else          $display("mult: TESTS FAILED, %0d of %0d products wrong", bad, ran);
`endif
        $finish;
    end
endmodule
