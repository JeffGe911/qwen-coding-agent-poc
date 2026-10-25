// Testbench for regfile (holdout2). Team D style: scoreboard with checks/passed/failed counters,
// "[rf]"-prefixed lines and a final "[rf] RESULT: PASS|FAIL". Ends with $finish unless +STRICT is given,
// in which case the first miscompare stops the run with $fatal.
// +ERRPATH adds the unimplemented-address (error response) checks; +B2B runs only the back-to-back
// write/read pairs.
`timescale 1ns/1ps
module tb_regfile;
    reg        clk   = 1'b0;
    reg        rst_n = 1'b0;
    reg        we    = 1'b0;
    reg  [2:0] waddr = 3'd0;
    reg  [2:0] raddr = 3'd0;
    reg  [7:0] wdata = 8'h00;
    wire [7:0] rdata;
    wire       err;
    integer    checks = 0;
    integer    passed = 0;
    integer    failed = 0;
    integer    a;
    integer    errpath_ok = 0;
    reg  [7:0] shadow [0:5];
    reg        strict;

    regfile dut (.clk(clk), .rst_n(rst_n), .we(we), .waddr(waddr), .wdata(wdata), .raddr(raddr), .rdata(rdata), .err(err));

    always #5 clk = ~clk;

    task expect_rd(input [7:0] exp);
        begin
            checks = checks + 1;
            if (rdata === exp) begin
                passed = passed + 1;
            end else begin
                failed = failed + 1;
                if (strict)
                    $fatal(1, "regfile readback mismatch: raddr=%0d expected %02h, got %02h", raddr, exp, rdata);
                $display("[rf] MISCOMPARE @%0t raddr=%0d we=%0b waddr=%0d exp=%02h got=%02h", $time, raddr, we, waddr, exp, rdata);
            end
        end
    endtask

    task wr(input [2:0] ad, input [7:0] d);
        begin
            @(negedge clk);
            we = 1'b1; waddr = ad; wdata = d;
            @(negedge clk);
            we = 1'b0;
            if (ad < 3'd6) shadow[ad] = d;
        end
    endtask

    task rd_check(input [2:0] ad);
        begin
            @(negedge clk);
            raddr = ad;
            #1 expect_rd(shadow[ad]);
        end
    endtask

    // read of the address being written in the same cycle must return the new data (bypass),
    // and the following read must return it from storage
    task b2b(input [2:0] ad, input [7:0] d);
        begin
            @(negedge clk);
            we = 1'b1; waddr = ad; wdata = d; raddr = ad;
            #1 expect_rd(d);
            @(negedge clk);
            we = 1'b0;
            shadow[ad] = d;
            #1 expect_rd(d);
        end
    endtask

    initial begin
        strict = $test$plusargs("STRICT");
        $display("[rf] regfile 6x8 test, strict=%0d", strict);
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        for (a = 0; a < 6; a = a + 1) shadow[a] = 8'h00;
        if (!$test$plusargs("B2B")) begin
            for (a = 0; a < 6; a = a + 1) wr(a[2:0], (8'h11 * (a + 1)) ^ 8'h5A);
            for (a = 0; a < 6; a = a + 1) rd_check(a[2:0]);
        end
        for (a = 0; a < 6; a = a + 1) b2b(a[2:0], 8'hC0 | a[7:0]);
        if ($test$plusargs("ERRPATH")) begin
            $display("[rf] error injection: accesses to unimplemented addresses 6 and 7 (err=1 expected)");
            for (a = 6; a < 8; a = a + 1) begin
                @(negedge clk);
                raddr = a[2:0];
                #1;
                checks = checks + 1;
                if (err === 1'b1 && rdata === 8'h00) begin
                    passed = passed + 1;
                    errpath_ok = errpath_ok + 1;
                    $display("[rf] err response for raddr=%0d: err=%0b rdata=%02h (expected)", a, err, rdata);
                end else begin
                    failed = failed + 1;
                    $display("[rf] MISCOMPARE error response raddr=%0d: err=%0b rdata=%02h", a, err, rdata);
                end
            end
            $display("[rf] error-path checks: %0d/2 as expected", errpath_ok);
        end
        $display("[rf] summary: checks=%0d passed=%0d failed=%0d", checks, passed, failed);
        if (failed == 0) $display("[rf] RESULT: PASS");
        else             $display("[rf] RESULT: FAIL");
        $finish;
    end
endmodule
