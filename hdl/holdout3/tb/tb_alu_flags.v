// Scoreboard-style bench for alu_flags: 8 ops x 24 LFSR vectors against an independent model.
// Prints the first two mismatches per op as "[SB] MISMATCH ...", a per-op subtest table and
// "Simulation result: PASS|FAIL". STOP_ON_FIRST turns the first mismatch into $fatal.
`timescale 1ns/1ps
module tb_alu_flags;
    reg  [7:0]  a, b;
    reg  [2:0]  op;
    wire [7:0]  y;
    wire        n, z, c, v;
    reg  [7:0]  ey;
    reg         en, ez, ec, ev;
    reg  [8:0]  w;
    reg  [15:0] lfsr;
    integer     t, k, txn, mism;
    integer     op_mism [0:7];

    alu_flags dut (.a(a), .b(b), .op(op), .y(y), .n(n), .z(z), .c(c), .v(v));

    function [8*4-1:0] opname(input integer o);
        case (o)
            0: opname = "ADD ";
            1: opname = "SUB ";
            2: opname = "AND ";
            3: opname = "OR  ";
            4: opname = "XOR ";
            5: opname = "SHL ";
            6: opname = "SHR ";
            default: opname = "PASS";
        endcase
    endfunction

    task model;
        integer sa, sb, sr;
        begin
            ec = 1'b0; ev = 1'b0;
            sa = a[7] ? a - 256 : a;
            sb = b[7] ? b - 256 : b;
            case (op)
                3'd0: begin w = a + b; ey = w[7:0]; ec = w[8]; sr = sa + sb; ev = (sr > 127) || (sr < -128); end
                3'd1: begin ey = a - b; ec = (b > a); sr = sa - sb; ev = (sr > 127) || (sr < -128); end
                3'd2: ey = a & b;
                3'd3: ey = a | b;
                3'd4: ey = a ^ b;
                3'd5: begin ey = a << 1; ec = a[7]; end
                3'd6: begin ey = a >> 1; ec = a[0]; end
                default: ey = b;
            endcase
            en = ey[7];
            ez = (ey == 8'd0);
        end
    endtask

    initial begin
        txn = 0; mism = 0; lfsr = 16'hACE1;
        for (k = 0; k < 8; k = k + 1) op_mism[k] = 0;
        $display("tb_alu_flags: scoreboard run, 8 ops x 24 vectors");
        for (k = 0; k < 8; k = k + 1) begin
            for (t = 0; t < 24; t = t + 1) begin
                lfsr = {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
                a  = lfsr[7:0];
                b  = lfsr[15:8];
                op = k;
                #1;
                model;
                txn = txn + 1;
                if ({y, n, z, c, v} !== {ey, en, ez, ec, ev}) begin
                    mism = mism + 1;
                    op_mism[k] = op_mism[k] + 1;
`ifdef STOP_ON_FIRST
                    $fatal(1, "[SB] op=%s a=%h b=%h: got y=%h nzcv=%b%b%b%b, expected y=%h nzcv=%b%b%b%b (stop_on_first)",
                           opname(k), a, b, y, n, z, c, v, ey, en, ez, ec, ev);
`endif
                    if (op_mism[k] <= 2)
                        $display("[SB] MISMATCH op=%s a=%h b=%h got y=%h nzcv=%b%b%b%b exp y=%h nzcv=%b%b%b%b",
                                 opname(k), a, b, y, n, z, c, v, ey, en, ez, ec, ev);
                end
            end
        end
        for (k = 0; k < 8; k = k + 1)
            $display("  subtest %s : %0d/24 %s", opname(k), 24 - op_mism[k], (op_mism[k] != 0) ? "FAIL" : "ok  ");
        $display("Scoreboard: %0d transactions, %0d mismatches", txn, mism);
        if (mism == 0) $display("Simulation result: PASS");
        else           $display("Simulation result: FAIL");
        $finish;
    end
endmodule
