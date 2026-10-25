// Testbench for uart_tx (holdout2). Team F style: serial decoder in the testbench, one line per byte,
// a busy-cycle watchdog and a "UART TB RESULT: PASS|FAIL (tb_uart_tx...)" verdict. Ends with $finish.
// +BAUD_NOTE: reports the slow-divider advisory through $warning.
// TB_V2:      enables the v2 receive-valid check.
`timescale 1ns/1ps
module tb_uart_tx;
    localparam integer CPB = 4;
    reg        clk   = 1'b0;
    reg        rst_n = 1'b0;
    reg        start = 1'b0;
    reg  [7:0] data  = 8'h00;
    wire       txd;
    wire       busy;
    integer    errs = 0;
    integer    n;
    integer    busy_cycles = 0;
    reg  [7:0] rx;
    reg  [7:0] bytes [0:3];

    uart_tx #(.CLKS_PER_BIT(4'd4)) dut (.clk(clk), .rst_n(rst_n), .start(start), .data(data), .txd(txd), .busy(busy));

    always #5 clk = ~clk;

    // watchdog: one frame is 40 clocks; busy must never stay high ten times that long
    always @(posedge clk) begin
        if (busy) busy_cycles = busy_cycles + 1;
        else      busy_cycles = 0;
        if (busy_cycles == 400) begin
            $display("*** WATCHDOG: busy stuck high for 400 clocks (frame is 40), aborting ***");
            $display("UART TB RESULT: FAIL (tb_uart_tx, watchdog)");
            $finish;
        end
    end

    task send_and_check(input [7:0] d);
        integer k;
        begin
            @(negedge clk);
            data = d; start = 1'b1;
            @(negedge clk);
            start = 1'b0;
            while (txd !== 1'b0) @(negedge clk);
            repeat (CPB / 2) @(negedge clk);
            for (k = 0; k < 8; k = k + 1) begin
                repeat (CPB) @(negedge clk);
                rx[k] = txd;
            end
            repeat (CPB) @(negedge clk);
            if (txd !== 1'b1) begin
                errs = errs + 1;
                $display("uart_tx_tb: framing error after 0x%02h", d);
            end
            if (rx !== d) begin
                errs = errs + 1;
                $display("uart_tx_tb: tx 0x%02h -> rx 0x%02h MISMATCH", d, rx);
            end else begin
                $display("uart_tx_tb: tx 0x%02h -> rx 0x%02h ok", d, rx);
            end
            while (busy) @(negedge clk);
        end
    endtask

    initial begin
        bytes[0] = 8'h55; bytes[1] = 8'hA3; bytes[2] = 8'h00; bytes[3] = 8'hFF;
        $display("uart_tx_tb: CLKS_PER_BIT=%0d, 4 bytes", CPB);
        if ($test$plusargs("BAUD_NOTE"))
            $warning("CLKS_PER_BIT=%0d is below the recommended 8; receiver sampling margin is reduced", CPB);
        repeat (3) @(negedge clk);
        rst_n = 1'b1;
        for (n = 0; n < 4; n = n + 1) send_and_check(bytes[n]);
`ifdef TB_V2
        if (rx_valid_q !== 1'b1) begin
            errs = errs + 1;
            $display("uart_tx_tb: receive-valid not seen");
        end
`endif
        if (errs == 0) $display("UART TB RESULT: PASS (tb_uart_tx)");
        else           $display("UART TB RESULT: FAIL (tb_uart_tx, %0d errors)", errs);
        $finish;
    end
endmodule
