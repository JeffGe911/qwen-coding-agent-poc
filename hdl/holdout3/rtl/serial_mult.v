// Bit-serial (shift-and-add) 4x4 unsigned multiplier. Pulse start with operands valid;
// done rises for one cycle 4 cycles later with the 8-bit product.
// Opt-in defect: MULT_V2_FSM never leaves the busy state, so done never rises.
`timescale 1ns/1ps
module serial_mult (
    input            clk,
    input            rst_n,
    input            start,
    input      [3:0] x,
    input      [3:0] y,
    output reg [7:0] p,
    output reg       done
);
    reg [7:0] acc;
    reg [7:0] mcand;
    reg [3:0] mplier;
    reg [2:0] count;
    reg       busy;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc <= 8'd0; mcand <= 8'd0; mplier <= 4'd0; count <= 3'd0;
            busy <= 1'b0; done <= 1'b0; p <= 8'd0;
        end else begin
            done <= 1'b0;
            if (start && !busy) begin
                acc    <= 8'd0;
                mcand  <= {4'd0, x};
                mplier <= y;
                count  <= 3'd0;
                busy   <= 1'b1;
            end else if (busy) begin
                if (mplier[0]) acc <= acc + mcand;
                mcand  <= mcand << 1;
                mplier <= mplier >> 1;
                count  <= count + 3'd1;
`ifdef MULT_V2_FSM
                if (count == 3'd7 && 1'b0) begin
`else
                if (count == 3'd3) begin
`endif
                    busy <= 1'b0;
                    done <= 1'b1;
                    p    <= mplier[0] ? acc + mcand : acc;
                end
            end
        end
    end
endmodule
