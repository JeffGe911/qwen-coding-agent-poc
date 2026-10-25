// Testbench for spi_shift (holdout2). Team G style: loopback slave model, one line per transfer, a $fatal
// watchdog (disabled with +NO_WDOG for long soak runs) and a closing "spi_tb: RESULT PASSED|FAILED" line.
`timescale 1ns/1ps
module tb_spi_shift;
    reg        clk   = 1'b0;
    reg        rst_n = 1'b0;
    reg        start = 1'b0;
    reg  [7:0] tx    = 8'h00;
    wire       sclk;
    wire       mosi;
    wire       cs_n;
    wire       done;
    wire [7:0] rx;
    reg        miso  = 1'b0;
    reg  [7:0] slave_out = 8'h00;
    reg  [7:0] slave_in  = 8'h00;
    reg  [2:0] sbit;
    integer    errs = 0;
    integer    t;
    reg  [7:0] txv [0:3];
    reg  [7:0] rxv [0:3];

    spi_shift dut (.clk(clk), .rst_n(rst_n), .start(start), .tx(tx), .miso(miso),
                   .sclk(sclk), .mosi(mosi), .cs_n(cs_n), .done(done), .rx(rx));

    always #5 clk = ~clk;

    // mode-0 slave model: presents bit 7 when selected, shifts on falling sclk, captures mosi on rising sclk
    always @(negedge cs_n) begin
        sbit = 3'd7;
        miso = slave_out[7];
        slave_in = 8'h00;
    end
    always @(posedge sclk) if (!cs_n) slave_in = {slave_in[6:0], mosi};
    always @(negedge sclk) if (!cs_n) begin
        sbit = sbit - 3'd1;
        miso = slave_out[sbit];
    end

    initial begin : watchdog
        if (!$test$plusargs("NO_WDOG")) begin
            #20000;
            $fatal(1, "spi_tb watchdog: transfer not finished after 20000 ns (cs_n=%b sclk=%b)", cs_n, sclk);
        end
    end

    task xfer(input integer i);
        begin
            slave_out = rxv[i];
            @(negedge clk);
            tx = txv[i]; start = 1'b1;
            @(negedge clk);
            start = 1'b0;
            @(posedge done);
            #1;
            if (rx !== rxv[i] || slave_in !== txv[i]) begin
                errs = errs + 1;
                $display("spi_tb: transfer %0d tx=%02h rx=%02h (slave saw %02h, sent %02h) BAD", i, txv[i], rx, slave_in, rxv[i]);
            end else begin
                $display("spi_tb: transfer %0d tx=%02h rx=%02h ok", i, txv[i], rx);
            end
        end
    endtask

    initial begin
        txv[0] = 8'hA5; txv[1] = 8'h3C; txv[2] = 8'h00; txv[3] = 8'hFF;
        rxv[0] = 8'h5A; rxv[1] = 8'hC3; rxv[2] = 8'h81; rxv[3] = 8'h7E;
        if ($test$plusargs("NO_WDOG")) $display("spi_tb: watchdog disabled (+NO_WDOG)");
        else                           $display("spi_tb: watchdog armed, 20000 ns");
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        for (t = 0; t < 4; t = t + 1) xfer(t);
        if (errs == 0) $display("spi_tb: RESULT PASSED (4/4 transfers)");
        else           $display("spi_tb: RESULT FAILED (%0d/4 transfers bad)", errs);
        $finish;
    end
endmodule
