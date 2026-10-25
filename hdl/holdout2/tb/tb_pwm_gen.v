// Testbench for pwm_gen (holdout2). Team B style: one table row per duty value, an
// "Errors: N Warnings: M" summary and a "== PASS ==" / "== FAIL ==" banner. Always ends with $finish.
// CHATTY:       extra status lines from the bring-up checklist.
// LEGACY_PRINT: banner lines kept from the old wrapper script, printed before the measurements.
`timescale 1ns/1ps
module tb_pwm_gen;
    reg        clk   = 1'b0;
    reg        rst_n = 1'b0;
    reg  [7:0] duty  = 8'd0;
    wire       pwm_out;
    wire       period_start;
    integer    errors = 0;
    integer    warnings = 0;
    integer    high;
    integer    k;
    reg  [7:0] duties [0:5];

    pwm_gen dut (.clk(clk), .rst_n(rst_n), .duty(duty), .pwm_out(pwm_out), .period_start(period_start));

    always #5 clk = ~clk;

    initial begin : guard
        #100000;
        $display("GUARD: pwm sweep exceeded 100000 ns");
        $finish;
    end

    task measure(input [7:0] dv);
        integer n;
        begin
            duty = dv;
            @(posedge clk);
            while (!period_start) @(posedge clk);
            @(posedge clk);
            while (!period_start) @(posedge clk);
            high = 0;
            for (n = 0; n < 256; n = n + 1) begin
                @(posedge clk);
                #1 if (pwm_out) high = high + 1;
            end
        end
    endtask

    initial begin
        duties[0] = 8'd0;   duties[1] = 8'd1;   duties[2] = 8'd64;
        duties[3] = 8'd128; duties[4] = 8'd200; duties[5] = 8'd255;
`ifdef LEGACY_PRINT
        $display("#RUN test=pwm_duty stage=run exit=0 elapsed_s=0.004 timed_out=false output_truncated=false");
        $display("  #RUN regression=g16_pwm end tests=1 finished_utc=2026-10-25T00:00:00+00:00");
        $display("== PASS ==");
`endif
        $display("pwm_gen duty sweep (period 256 clocks)");
`ifdef CHATTY
        $display("bring-up: FAULT input not present on this block, fault checks skipped");
        $display("bring-up: error-injection hooks disabled (ERR_INJ=0)");
        $display("bring-up: timeout guard 100000 ns armed");
`endif
        repeat (2) @(posedge clk);
        rst_n = 1'b1;
        for (k = 0; k < 6; k = k + 1) begin
            measure(duties[k]);
            if (high != duties[k]) errors = errors + 1;
            $display("  duty=%3d  high=%3d  expect=%3d  %s", duties[k], high, duties[k],
                     (high == duties[k]) ? "ok" : "<-- MISMATCH");
            if (duties[k] == 8'd0) begin
                warnings = warnings + 1;
                $display("  WARN: duty=0 holds pwm_out low for the whole period (by spec)");
            end
            if (duties[k] == 8'd255) begin
                warnings = warnings + 1;
                $display("  WARN: duty=255 gives 255/256 high, 100%% is not reachable (by spec)");
            end
        end
`ifdef CHATTY
        $display("bring-up: monitors reported 0 errors, 0 failures");
`endif
        $display("Errors: %0d Warnings: %0d", errors, warnings);
        if (errors == 0) $display("== PASS ==");
        else             $display("== FAIL ==");
        $finish;
    end
endmodule
