// 8-bit ALU used by the regression-triage examples. Written for this PoC.
// Defects are opt-in through defines so one source tree yields passing and failing runs.
module alu8 (
    input  [7:0] a,
    input  [7:0] b,
    input  [1:0] op,
    output reg [7:0] y,
    output reg carry
);
    always @* begin
        carry = 1'b0;
        case (op)
            2'd0: {carry, y} = a + b;
`ifdef BUG_SUB
            2'd1: {carry, y} = a + b;                 // injected defect: SUB behaves like ADD
`else
            2'd1: {carry, y} = {1'b0, a} - {1'b0, b};
`endif
            2'd2: y = a & b;
            default: y = a ^ b;
        endcase
`ifdef BUG_SYNTAX
        y = y                                         // injected compile error: missing semicolon
`endif
    end
endmodule
