// Push-button debouncer for the holdout2 regression set (new design, not derived from hdl/rtl).
// A two-flop synchronizer feeds a stability counter; clean takes the new input value only after the
// synchronized input has differed from clean for STABLE_CYCLES consecutive clocks.
// REV_B selects the B-step acceptance window (terminal count two short).
module debounce #(
    parameter [3:0] STABLE_CYCLES = 4'd8
) (
    input  wire clk,
    input  wire rst_n,
    input  wire noisy,
    output reg  clean
);
`ifdef REV_B
    localparam [3:0] LAST = STABLE_CYCLES - 4'd3;
`else
    localparam [3:0] LAST = STABLE_CYCLES - 4'd1;
`endif

    reg       sync0;
    reg       sync1;
    reg [3:0] count;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sync0 <= 1'b0;
            sync1 <= 1'b0;
            count <= 4'd0;
            clean <= 1'b0;
        end else begin
            sync0 <= noisy;
            sync1 <= sync0;
            if (sync1 == clean) begin
                count <= 4'd0;
            end else if (count == LAST) begin
                clean <= sync1;
                count <= 4'd0;
            end else begin
                count <= count + 4'd1;
            end
        end
    end
endmodule
