// Testbench for sync_fifo with SystemVerilog immediate assertions (compile with -g2012).
// A broken full flag stops the run through $fatal, so the simulator exits non-zero.
`timescale 1ns/1ps
module tb_sync_fifo;
    reg        clk = 1'b0, rst_n = 1'b0, wr_en = 1'b0, rd_en = 1'b0;
    reg  [7:0] din = 8'd0;
    wire [7:0] dout;
    wire       full, empty;
    wire [2:0] count;
    integer    k;

    sync_fifo #(.WIDTH(8), .DEPTH(4)) dut (
        .clk(clk), .rst_n(rst_n), .wr_en(wr_en), .din(din), .rd_en(rd_en),
        .dout(dout), .full(full), .empty(empty), .count(count)
    );

    always #5 clk = ~clk;

    initial begin
        $display("tb_sync_fifo: start");
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        for (k = 0; k < 4; k = k + 1) begin
            @(negedge clk);
            wr_en = 1'b1; din = 8'hA0 + k;
            if (k == 3) assert (!full) else $fatal(1, "fifo reports full after %0d writes (count=%0d, DEPTH=4)", k, count);
        end
        @(negedge clk); wr_en = 1'b0;
        assert (full) else $fatal(1, "fifo not full after 4 writes (count=%0d)", count);
        for (k = 0; k < 4; k = k + 1) begin
            @(negedge clk); rd_en = 1'b1;
            @(negedge clk); rd_en = 1'b0;
            assert (dout == 8'hA0 + k) else $error("read %0d: expected %h got %h", k, 8'hA0 + k, dout);
        end
        assert (empty) else $error("fifo not empty after 4 reads (count=%0d)", count);
        $display("TEST PASSED: tb_sync_fifo");
        $finish;
    end
endmodule
