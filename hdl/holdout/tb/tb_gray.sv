// Holdout testbench for bin2gray/gray2bin: exhaustive over all 5-bit codes.
// Checks the encoding against b ^ (b >> 1), the decode round trip and the one-bit-change property.
// Prints "MISMATCH @<t>: ..." (first six) and a "*** TEST PASSED ***" / "*** TEST FAILED ***" banner,
// then $finish, so the simulator exits 0 either way. DUMP_VCD writes tb_gray.vcd.
`timescale 1ns/1ps
module tb_gray;
    localparam W = 5;
    reg  [W-1:0] bin = {W{1'b0}};
    wire [W-1:0] gray, back;
    reg  [W-1:0] prev_gray = {W{1'b0}}, ref_gray, diff;
    integer      v, checks = 0, wrong = 0, shown = 0;

`ifdef BUG_MODNAME
    gray_encoder #(.W(W)) enc (.bin(bin), .gray(gray));   // injected defect: the module is called bin2gray
`else
    bin2gray #(.W(W)) enc (.bin(bin), .gray(gray));
`endif
    gray2bin #(.W(W)) dec (.gray(gray), .bin(back));

    task report(input string what, input [W-1:0] exp_v, input [W-1:0] act_v);
        begin
            wrong = wrong + 1;
            if (shown < 6) begin
                shown = shown + 1;
                $display("MISMATCH @%0t: %s bin=%b exp=%b act=%b", $time, what, bin, exp_v, act_v);
            end
        end
    endtask

    initial begin
`ifdef DUMP_VCD
        $dumpfile("tb_gray.vcd");
        $dumpvars(0, tb_gray);
`endif
        $display("tb_gray: exhaustive check of %0d codes", 1 << W);
        for (v = 0; v < (1 << W); v = v + 1) begin
            bin = v;
            #1;
            ref_gray = bin ^ (bin >> 1);
            checks = checks + 2;
            if (gray !== ref_gray) report("encode", ref_gray, gray);
            if (back !== bin) report("decode", bin, back);
            if (v > 0) begin
                checks = checks + 1;
                diff = gray ^ prev_gray;
                if (diff == 0 || (diff & (diff - 1'b1)) != 0) report("adjacent", prev_gray, gray);
            end
            prev_gray = gray;
        end
        if (shown < wrong) $display("... %0d further mismatch(es) not shown", wrong - shown);
        if (wrong == 0) $display("*** TEST PASSED *** tb_gray (%0d checks)", checks);
        else            $display("*** TEST FAILED *** tb_gray: %0d of %0d checks wrong", wrong, checks);
        $finish;
    end
endmodule
