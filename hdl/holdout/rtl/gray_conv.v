// Holdout design: binary <-> Gray-code converters (combinational).
// Written for the regression-triage holdout split; defects are opt-in through defines.
module bin2gray #(
    parameter W = 5
) (
    input  [W-1:0] bin,
    output [W-1:0] gray
);
`ifdef BUG_GRAY_LSB
    assign gray = {bin[W-1:1] ^ (bin[W-1:1] >> 1), bin[0]}; // injected defect: LSB is not XORed with bit 1
`else
    assign gray = bin ^ (bin >> 1);
`endif
endmodule

module gray2bin #(
    parameter W = 5
) (
    input      [W-1:0] gray,
    output reg [W-1:0] bin
);
    integer i;
    always @* begin
        bin[W-1] = gray[W-1];
        for (i = W - 2; i >= 0; i = i - 1)
            bin[i] = bin[i+1] ^ gray[i];
    end
endmodule
