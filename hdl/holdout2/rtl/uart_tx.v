// UART transmitter, 8N1, LSB first, CLKS_PER_BIT clocks per bit (holdout2 design).
// busy is high from the accepted start request until the end of the stop bit.
// REV_E: stop-bit timer from the low-power variant (its tick enable is never asserted).
module uart_tx #(
    parameter [3:0] CLKS_PER_BIT = 4'd4
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,
    input  wire [7:0] data,
    output reg        txd,
    output reg        busy
);
    localparam [1:0] S_IDLE  = 2'd0;
    localparam [1:0] S_START = 2'd1;
    localparam [1:0] S_DATA  = 2'd2;
    localparam [1:0] S_STOP  = 2'd3;
    localparam [3:0] LAST    = CLKS_PER_BIT - 4'd1;

    reg [1:0] st;
    reg [2:0] bitn;
    reg [7:0] sh;
    reg [3:0] tick;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st   <= S_IDLE;
            txd  <= 1'b1;
            busy <= 1'b0;
            bitn <= 3'd0;
            sh   <= 8'h00;
            tick <= 4'd0;
        end else begin
            case (st)
                S_IDLE: begin
                    if (start) begin
                        sh   <= data;
                        busy <= 1'b1;
                        txd  <= 1'b0;
                        tick <= 4'd0;
                        st   <= S_START;
                    end
                end
                S_START: begin
                    if (tick == LAST) begin
                        tick <= 4'd0;
                        txd  <= sh[0];
                        bitn <= 3'd0;
                        st   <= S_DATA;
                    end else begin
                        tick <= tick + 4'd1;
                    end
                end
                S_DATA: begin
                    if (tick == LAST) begin
                        tick <= 4'd0;
                        if (bitn == 3'd7) begin
                            txd <= 1'b1;
                            st  <= S_STOP;
                        end else begin
                            bitn <= bitn + 3'd1;
                            sh   <= {1'b0, sh[7:1]};
                            txd  <= sh[1];
                        end
                    end else begin
                        tick <= tick + 4'd1;
                    end
                end
                S_STOP: begin
                    if (tick == LAST) begin
                        tick <= 4'd0;
                        busy <= 1'b0;
                        st   <= S_IDLE;
                    end else begin
`ifdef REV_E
                        tick <= tick;
`else
                        tick <= tick + 4'd1;
`endif
                    end
                end
                default: st <= S_IDLE;
            endcase
        end
    end
endmodule
