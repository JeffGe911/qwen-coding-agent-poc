// Clock divider: clk_out toggles every DIV input cycles (output period = 2*DIV input periods).
// Opt-in defect: DIV_GLITCHFREE keeps clk_out at its reset value.
module clk_div #(parameter integer DIV = 3) (
    input      clk,
    input      rst_n,
    output reg clk_out
);
    reg [7:0] cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt     <= 8'd0;
            clk_out <= 1'b0;
        end else if (cnt == DIV - 1) begin
            cnt <= 8'd0;
`ifdef DIV_GLITCHFREE
            clk_out <= clk_out;
`else
            clk_out <= ~clk_out;
`endif
        end else begin
            cnt <= cnt + 8'd1;
        end
    end
endmodule
