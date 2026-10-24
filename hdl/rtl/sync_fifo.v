// Small synchronous FIFO used by the regression-triage examples. Written for this PoC.
module sync_fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 4
) (
    input                  clk,
    input                  rst_n,
    input                  wr_en,
    input  [WIDTH-1:0]     din,
    input                  rd_en,
    output reg [WIDTH-1:0] dout,
    output                 full,
    output                 empty,
    output reg [2:0]       count
);
    reg [WIDTH-1:0] mem [0:DEPTH-1];
    reg [1:0] wptr, rptr;
`ifdef BUG_FULL_FLAG
    assign full = (count == DEPTH - 1);               // injected defect: reports full one entry early
`else
    assign full = (count == DEPTH);
`endif
    assign empty = (count == 0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wptr <= 0; rptr <= 0; count <= 0; dout <= 0;
        end else begin
            if (wr_en && !full) begin
                mem[wptr] <= din;
                wptr <= wptr + 1'b1;
            end
            if (rd_en && !empty) begin
                dout <= mem[rptr];
                rptr <= rptr + 1'b1;
            end
            case ({wr_en && !full, rd_en && !empty})
                2'b10: count <= count + 1'b1;
                2'b01: count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end
endmodule
