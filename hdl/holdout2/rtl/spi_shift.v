// SPI-style mode-0 shifter (holdout2 design): on start, sends tx MSB first on mosi while sampling
// miso on each rising sclk edge; sclk runs at clk/2. After eight bits cs_n rises, rx holds the
// received byte and done pulses for one clock.
// REV_H: bit counter terminal compare from the 16-bit variant (widened constant).
module spi_shift (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,
    input  wire [7:0] tx,
    input  wire       miso,
    output reg        sclk,
    output reg        mosi,
    output reg        cs_n,
    output reg        done,
    output reg  [7:0] rx
);
    reg [7:0] sh_tx;
    reg [7:0] sh_rx;
    reg [2:0] cnt;
    reg       active;

`ifdef REV_H
    wire last_bit = ({1'b0, cnt} == 4'd8);
`else
    wire last_bit = (cnt == 3'd7);
`endif

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sclk   <= 1'b0;
            mosi   <= 1'b0;
            cs_n   <= 1'b1;
            done   <= 1'b0;
            rx     <= 8'h00;
            sh_tx  <= 8'h00;
            sh_rx  <= 8'h00;
            cnt    <= 3'd0;
            active <= 1'b0;
        end else begin
            done <= 1'b0;
            if (!active) begin
                if (start) begin
                    active <= 1'b1;
                    cs_n   <= 1'b0;
                    sh_tx  <= tx;
                    mosi   <= tx[7];
                    cnt    <= 3'd0;
                    sclk   <= 1'b0;
                end
            end else if (!sclk) begin
                sclk  <= 1'b1;
                sh_rx <= {sh_rx[6:0], miso};
            end else begin
                sclk <= 1'b0;
                if (last_bit) begin
                    active <= 1'b0;
                    cs_n   <= 1'b1;
                    done   <= 1'b1;
                    rx     <= sh_rx;
                end else begin
                    cnt   <= cnt + 3'd1;
                    sh_tx <= {sh_tx[6:0], 1'b0};
                    mosi  <= sh_tx[6];
                end
            end
        end
    end
endmodule
