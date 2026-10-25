// Six-entry, 8-bit register file with a 3-bit address space (holdout2 design).
// Synchronous write, asynchronous read with write-through bypass (a read of the address being written
// in the same cycle returns the new data). Addresses 6 and 7 are unimplemented: err is raised and
// reads return 8'h00.
// ECO_WE:  write-enable decode from the ECO netlist (entry 3 never written).
// ECO_BYP: bypass path removed (read-during-write returns the old contents).
module regfile (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       we,
    input  wire [2:0] waddr,
    input  wire [7:0] wdata,
    input  wire [2:0] raddr,
    output reg  [7:0] rdata,
    output wire       err
);
    reg [7:0] mem [0:5];

`ifdef ECO_WE
    wire w_ok = we && (waddr < 3'd6) && (waddr != 3'd3);
`else
    wire w_ok = we && (waddr < 3'd6);
`endif

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mem[0] <= 8'h00;
            mem[1] <= 8'h00;
            mem[2] <= 8'h00;
            mem[3] <= 8'h00;
            mem[4] <= 8'h00;
            mem[5] <= 8'h00;
        end else if (w_ok) begin
            mem[waddr] <= wdata;
        end
    end

    assign err = (raddr > 3'd5) || (we && (waddr > 3'd5));

    always @* begin
        if (raddr > 3'd5)
            rdata = 8'h00;
`ifndef ECO_BYP
        else if (we && (waddr == raddr))
            rdata = wdata;
`endif
        else
            rdata = mem[raddr];
    end
endmodule
