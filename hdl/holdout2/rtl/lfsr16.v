// 16-bit Galois LFSR (x^16 + x^14 + x^13 + x^11 + 1), right-shifting, seed 16'hACE1 (holdout2 design).
// wrap is high whenever the register holds the seed value again.
// REV_C: wrap detector compares only the low byte (area-reduced ECO).
// REV_K: tap constant taken from a v2 package parameter that this tree does not define.
module lfsr16 (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        en,
    output reg  [15:0] state,
    output wire        wrap
);
    localparam [15:0] SEED = 16'hACE1;
`ifdef REV_K
    localparam [15:0] TAPS = TAPS_V2;
`else
    localparam [15:0] TAPS = 16'hB400;
`endif

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= SEED;
        else if (en)
            state <= (state >> 1) ^ (state[0] ? TAPS : 16'h0000);
    end

`ifdef REV_C
    assign wrap = (state[7:0] == SEED[7:0]);
`else
    assign wrap = (state == SEED);
`endif
endmodule
