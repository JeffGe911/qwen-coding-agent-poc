// Holdout design: shift register with parallel load and serial in/out (shifts towards the MSB).
// Written for the regression-triage holdout split; defects are opt-in through defines.
module shift_reg #(
    parameter W = 8
) (
    input          clk,
    input          rst_n,
    input          load,      // parallel load from pin
    input          shift_en,  // shift one place; sin enters at bit 0
    input          sin,
    input  [W-1:0] pin,
    output [W-1:0] q,
    output         sout       // bit W-1, the next bit to leave
);
`ifdef BUG_LVALUE
    wire [W-1:0] q_r;                                   // injected defect: declared as a net but assigned in an always block
`else
    reg  [W-1:0] q_r;
`endif

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            q_r <= {W{1'b0}};
        else if (load)
            q_r <= pin;
        else if (shift_en)
            q_r <= {q_r[W-2:0], sin};
    end

    assign q    = q_r;
    assign sout = q_r[W-1];
endmodule
