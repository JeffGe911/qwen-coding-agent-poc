// Holdout testbench for rr_arbiter. Requester 0 asks on every cycle; the sequence then waits until
// requesters 2, 3 and 1 have each been served once. Every cycle the grant must be one-hot (or zero)
// and may only go to a requester that was asking. A 3000 ns watchdog stops a run that makes no progress.
// Last line before $finish: "Simulation PASSED (tb_rr_arbiter)" or "Simulation FAILED (tb_rr_arbiter): <why>".
`timescale 1ns/1ps
module tb_rr_arbiter;
    reg        clk = 1'b0, rst_n = 1'b0;
    reg  [3:0] req = 4'b0000, req_s = 4'b0000;
    wire [3:0] grant;
    integer    waiting_for = -1, served = 0, bad = 0, grants = 0;

`ifdef BUG_PORTNAME
    rr_arbiter dut (.clk(clk), .rst_n(rst_n), .request(req), .grant(grant));  // injected defect: the port is called req
`else
    rr_arbiter dut (.clk(clk), .rst_n(rst_n), .req(req), .grant(grant));
`endif

    always #5 clk = ~clk;

    always @(posedge clk) req_s <= req;    // what the arbiter saw on this edge

    always @(negedge clk) if (rst_n) begin
        if (grant != 4'b0000) grants = grants + 1;
        if ((grant & (grant - 1'b1)) != 4'b0000) begin
            bad = bad + 1;
            $display("tb_rr_arbiter: grant=%b is not one-hot at %0t ns", grant, $time);
        end
        if ((grant & ~req_s) != 4'b0000) begin
            bad = bad + 1;
            $display("tb_rr_arbiter: grant=%b given without a request (req=%b) at %0t ns", grant, req_s, $time);
        end
    end

    initial begin : watchdog
        #3000;
        $display("WATCHDOG: no progress for 3000 ns (still waiting for grant[%0d]); stopping simulation", waiting_for);
        $display("Simulation FAILED (tb_rr_arbiter): watchdog expired");
        $finish;
    end

    task serve(input integer who, input [3:0] pattern);
        begin
            @(posedge clk); #1 req = pattern | 4'b0001;
            waiting_for = who;
            @(negedge clk);
            while (!grant[who]) @(negedge clk);
            served = served + 1;
            $display("tb_rr_arbiter: requester %0d served at %0t ns (req=%b)", who, $time, req);
        end
    endtask

    initial begin
        $display("tb_rr_arbiter: start");
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        serve(2, 4'b0100);
        serve(3, 4'b1010);
        serve(1, 4'b0010);
        @(posedge clk); #1 req = 4'b0000;
        repeat (3) @(negedge clk);
        if (bad == 0) $display("Simulation PASSED (tb_rr_arbiter) %0d requesters served, %0d grant cycles checked", served, grants);
        else          $display("Simulation FAILED (tb_rr_arbiter): %0d protocol violation(s)", bad);
        $finish;
    end
endmodule
