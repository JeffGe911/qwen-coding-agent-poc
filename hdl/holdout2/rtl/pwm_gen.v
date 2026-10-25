// 8-bit PWM generator (holdout2 design). pwm_out is high for `duty` clocks of every 256-clock period.
// FAST_CMP: comparator variant from an ECO candidate (uses <=, one extra high clock per period).
// REV_W:    counter increment from the 9-bit prescaler branch (same behaviour, wider constant).
module pwm_gen (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [7:0] duty,
    output reg        pwm_out,
    output wire       period_start
);
    reg [7:0] cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            cnt <= 8'd0;
        else
`ifdef REV_W
            cnt <= cnt + 9'd1;
`else
            cnt <= cnt + 8'd1;
`endif
    end

    assign period_start = (cnt == 8'd0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            pwm_out <= 1'b0;
        else
`ifdef FAST_CMP
            pwm_out <= (cnt <= duty);
`elsif REV_S
            pwm_out <= (cnt < duty)
`else
            pwm_out <= (cnt < duty);
`endif
    end
endmodule
