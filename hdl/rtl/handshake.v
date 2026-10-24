// Request/acknowledge responder: raises ack four cycles after req. Written for this PoC.
module handshake (
    input      clk,
    input      rst_n,
    input      req,
    output reg ack
);
    reg [2:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ack <= 1'b0; cnt <= 3'd0;
        end else if (req && !ack) begin
`ifdef BUG_NO_ACK
            cnt <= cnt;                               // injected defect: counter stuck, ack never rises
`else
            cnt <= cnt + 1'b1;
`endif
            if (cnt == 3'd3) ack <= 1'b1;
        end else if (!req) begin
            ack <= 1'b0; cnt <= 3'd0;
        end
    end
endmodule
