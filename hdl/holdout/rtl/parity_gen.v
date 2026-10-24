// Holdout design: even/odd parity generator with a receive-side checker.
// Written for the regression-triage holdout split; defects are opt-in through defines.
module parity_gen #(
    parameter W = 8
) (
    input  [W-1:0] data,
    input          odd,      // 1: odd parity, 0: even parity
    input          chk_bit,  // parity bit that arrived with data
    output         parity,   // parity bit to append to data
    output         perr      // data + chk_bit violate the selected parity
);
`ifdef BUG_PARITY_ODD
    assign parity = ^data;                              // injected defect: odd/even select ignored
`else
    assign parity = (^data) ^ odd;
`endif

`ifdef BUG_MULTI_DRIVER
    reg perr_r;
    assign perr = perr_r;
    always @* perr_r = parity ^ chk_bit;
    assign perr_r = 1'b0;                               // injected defect: perr_r is also driven continuously
`else
    assign perr = parity ^ chk_bit;
`endif
endmodule
