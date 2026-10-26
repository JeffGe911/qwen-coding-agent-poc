// 8-bit ALU with N/Z/C/V flags. op: 0 ADD, 1 SUB, 2 AND, 3 OR, 4 XOR, 5 SHL, 6 SHR, 7 PASS-B.
// C is the carry out of ADD, the borrow of SUB and the shifted-out bit of SHL/SHR; V is signed overflow.
// Opt-in defect: ALU_FAST_FLAGS computes V for SUB with the ADD formula.
module alu_flags (
    input      [7:0] a,
    input      [7:0] b,
    input      [2:0] op,
    output reg [7:0] y,
    output reg       n,
    output reg       z,
    output reg       c,
    output reg       v
);
    reg [8:0] wide;

    always @* begin
        wide = 9'd0;
        c = 1'b0;
        v = 1'b0;
        case (op)
            3'd0: begin
                wide = {1'b0, a} + {1'b0, b};
                y = wide[7:0];
                c = wide[8];
                v = (a[7] == b[7]) && (y[7] != a[7]);
            end
            3'd1: begin
                wide = {1'b0, a} - {1'b0, b};
                y = wide[7:0];
                c = wide[8];
`ifdef ALU_FAST_FLAGS
                v = (a[7] == b[7]) && (y[7] != a[7]);
`else
                v = (a[7] != b[7]) && (y[7] != a[7]);
`endif
            end
            3'd2: y = a & b;
            3'd3: y = a | b;
            3'd4: y = a ^ b;
            3'd5: begin y = {a[6:0], 1'b0}; c = a[7]; end
            3'd6: begin y = {1'b0, a[7:1]}; c = a[0]; end
            default: y = b;
        endcase
        n = y[7];
        z = (y == 8'd0);
    end
endmodule
