// Two-digit BCD up-counter (00..99) with enable and a terminal-count output.
// Opt-in defects: BCD_CARRY_LOOKAHEAD lets the ones digit reach 4'hA before wrapping,
// BCD_ASYNC_LOAD contains a mistyped keyword.
module bcd_counter (
    input            clk,
    input            rst,
    input            en,
    output reg [3:0] ones,
    output reg [3:0] tens,
    output           tc
);
    assign tc = en && (ones == 4'd9) && (tens == 4'd9);

    always @(posedge clk) begin
        if (rst) begin
            ones <= 4'd0;
            tens <= 4'd0;
        end else if (en) begin
`ifdef BCD_CARRY_LOOKAHEAD
            if (ones == 4'd10) begin
`else
            if (ones == 4'd9) begin
`endif
                ones <= 4'd0;
                tens <= (tens == 4'd9) ? 4'd0 : tens + 4'd1;
            end
`ifdef BCD_ASYNC_LOAD
            elsif (1'b1) ones <= ones + 4'd1;
`else
            else ones <= ones + 4'd1;
`endif
        end
    end
endmodule
