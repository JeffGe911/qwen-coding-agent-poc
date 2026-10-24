// Holdout design: up/down counter with count enable and synchronous parallel load.
// Written for the regression-triage holdout split, independently of the dev designs.
// Defects are opt-in through defines so one source tree yields passing and failing runs.
module updown_counter #(
    parameter W = 8
) (
    input              clk,
    input              rst_n,
    input              en,
    input              up,
    input              load,
    input  [W-1:0]     d,
    output reg [W-1:0] q,
    output             wrap
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            q <= {W{1'b0}};
        else if (load)
            q <= d;
        else if (en) begin
            if (up)
                q <= q + 1'b1;
            else
`ifdef BUG_DOWN_STEP
                q <= q - 2'd2;                          // injected defect: counts down by two
`else
                q <= q - 1'b1;
`endif
        end
    end

`ifdef BUG_UNDECLARED
    assign wrap = en_q & (up ? &q : ~|q);               // injected defect: en_q is never declared
`else
    assign wrap = en & (up ? &q : ~|q);
`endif
endmodule
