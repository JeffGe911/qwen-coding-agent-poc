// Holdout design: 4-way round-robin arbiter with a registered one-hot grant.
// The requester after the last granted one has the highest priority.
// Written for the regression-triage holdout split; defects are opt-in through defines.
module rr_arbiter (
    input            clk,
    input            rst_n,
    input      [3:0] req,
    output reg [3:0] grant
);
    reg [1:0] last;
    reg [3:0] pick;

    always @* begin
        case (last)
            2'd0:    pick = req[1] ? 4'b0010 : req[2] ? 4'b0100 : req[3] ? 4'b1000 : req[0] ? 4'b0001 : 4'b0000;
            2'd1:    pick = req[2] ? 4'b0100 : req[3] ? 4'b1000 : req[0] ? 4'b0001 : req[1] ? 4'b0010 : 4'b0000;
            2'd2:    pick = req[3] ? 4'b1000 : req[0] ? 4'b0001 : req[1] ? 4'b0010 : req[2] ? 4'b0100 : 4'b0000;
            default: pick = req[0] ? 4'b0001 : req[1] ? 4'b0010 : req[2] ? 4'b0100 : req[3] ? 4'b1000 : 4'b0000;
        endcase
    end

    function [1:0] onehot_index(input [3:0] oh);
        case (oh)
            4'b0010: onehot_index = 2'd1;
            4'b0100: onehot_index = 2'd2;
            4'b1000: onehot_index = 2'd3;
            default: onehot_index = 2'd0;
        endcase
    endfunction

`ifdef LINT_WIDTH
    // injected lint defect: a 3-bit sum is squeezed into the 2-bit pointer
    wire [1:0] next_last = onehot_index(pick) + 3'd1;
`endif

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            grant <= 4'b0000;
            last  <= 2'd3;
        end else begin
            grant <= pick;
            if (pick != 4'b0000)
`ifdef BUG_RR_STUCK
                last <= 2'd3;                           // injected defect: pointer never advances, requester 0 always wins
`else
                last <= onehot_index(pick);
`endif
        end
    end
endmodule
