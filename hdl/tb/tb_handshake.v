// Testbench for handshake with a watchdog. NO_FINISH removes both the watchdog and $finish,
// so the simulation never ends by itself and only the regression runner's wall-clock limit stops it.
`timescale 1ns/1ps
module tb_handshake;
    reg  clk = 1'b0, rst_n = 1'b0, req = 1'b0;
    wire ack;
    integer cycles = 0;

    handshake dut (.clk(clk), .rst_n(rst_n), .req(req), .ack(ack));

    always #5 clk = ~clk;

`ifndef NO_FINISH
    initial begin : watchdog
        #2000;
        $display("ERROR: [%0t] TIMEOUT watchdog: ack not seen within 2000 ns after req", $time);
        $display("TEST FAILED: tb_handshake (timeout)");
        $finish;
    end
`endif

    initial begin
        $display("tb_handshake: start");
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        @(negedge clk); req = 1'b1;
        while (!ack) begin
            @(posedge clk);
            cycles = cycles + 1;
        end
        $display("tb_handshake: ack after %0d cycles", cycles);
        @(negedge clk); req = 1'b0;
`ifndef NO_FINISH
        $display("TEST PASSED: tb_handshake");
        $finish;
`endif
    end
endmodule
