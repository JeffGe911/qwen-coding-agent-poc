// SystemVerilog bench for prio_arbiter: all 16 request patterns, immediate assertions on every grant.
// Assertion failures are reported with $error (simulation continues); the bench prints
// "*** SIMULATION PASSED ***" or "*** SIMULATION FAILED ***" and then calls $finish.
`timescale 1ns/1ps
module tb_prio_arbiter;
    logic       clk = 1'b0;
    logic       rst_n = 1'b0;
    logic [3:0] req;
    logic [3:0] gnt;
    int         n_err = 0;
    int         n_chk = 0;

    prio_arbiter #(.N(4)) dut (.clk(clk), .rst_n(rst_n), .req(req), .gnt(gnt));

    always #4 clk = ~clk;

    function automatic logic [3:0] model(input logic [3:0] r);
        for (int k = 0; k < 4; k++)
            if (r[k]) return 4'b0001 << k;
        return 4'b0000;
    endfunction

`ifdef ARB_SVA
    a_onehot: assert property (@(posedge clk) disable iff (!rst_n) ((gnt & (gnt - 4'd1)) == 4'd0));
`endif

    initial begin
        $display("== tb_prio_arbiter: exhaustive request patterns, req[0] highest priority ==");
        #1 req = 4'b0000;
        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        for (int p = 0; p < 16; p++) begin
            @(negedge clk) req = p[3:0];
            @(posedge clk);
            #1;
            n_chk++;
            assert ((gnt & (gnt - 4'd1)) == 4'd0)
                else begin n_err++; $error("grant not one-hot: req=%b gnt=%b", req, gnt); end
            assert (gnt == model(req))
                else begin n_err++; $error("wrong grant: req=%b gnt=%b expected=%b", req, gnt, model(req)); end
        end
        if (n_err == 0) $display("*** SIMULATION PASSED *** (%0d patterns checked)", n_chk);
        else            $display("*** SIMULATION FAILED *** (%0d assertion failures in %0d patterns)", n_err, n_chk);
        $finish;
    end
endmodule
