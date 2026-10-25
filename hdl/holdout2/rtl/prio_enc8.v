// 8-input priority encoder, highest index wins (holdout2 design). valid is low when no request is set.
// LSB_FIRST: priority order of the legacy block (lowest index wins).
// REV_D:     hand-edited decode table from a merge.
module prio_enc8 (
    input  wire [7:0] req,
    output reg  [2:0] idx,
    output wire       valid
);
    assign valid = |req;

    always @* begin
`ifdef LSB_FIRST
        casez (req)
            8'b???????1: idx = 3'd0;
            8'b??????10: idx = 3'd1;
            8'b?????100: idx = 3'd2;
            8'b????1000: idx = 3'd3;
            8'b???10000: idx = 3'd4;
            8'b??100000: idx = 3'd5;
            8'b?1000000: idx = 3'd6;
            8'b10000000: idx = 3'd7;
            default:     idx = 3'd0;
        endcase
`else
        casez (req)
            8'b1???????: idx = 3'd7;
            8'b01??????: idx = 3'd6;
`ifdef REV_D
            8'b001?????: idx = 3'd5
`else
            8'b001?????: idx = 3'd5;
`endif
            8'b0001????: idx = 3'd4;
            8'b00001???: idx = 3'd3;
            8'b000001??: idx = 3'd2;
            8'b0000001?: idx = 3'd1;
            default:     idx = 3'd0;
        endcase
`endif
    end
endmodule
