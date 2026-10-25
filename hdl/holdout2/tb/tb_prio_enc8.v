// Testbench for prio_enc8 (holdout2). Team E style: exhaustive vector sweep, up to five failing vectors
// listed, then one "PASS: tb_prio_enc8 (...)" or "FAIL: tb_prio_enc8 (...)" line. Ends with $finish.
// DBG_PORT:    idx observed through the 4-bit debug bus of the bring-up harness (upper bit unused), with
//              a waveform dump.
// SPLIT_PHASE: sweep split in two phases; phase 2 is released by an event from the sequencer
//              (SEQ_V1 provides it).
`timescale 1ns/1ps
module tb_prio_enc8;
    reg  [7:0] req;
    wire       valid;
`ifdef DBG_PORT
    wire [3:0] idx_bus;
    wire [2:0] idx = idx_bus[2:0];
    prio_enc8 dut (.req(req), .idx(idx_bus), .valid(valid));
`else
    wire [2:0] idx;
    prio_enc8 dut (.req(req), .idx(idx), .valid(valid));
`endif
    integer    v;
    integer    j;
    integer    bad = 0;
    reg  [2:0] exp_idx;
    event      phase2_go;

`ifdef SEQ_V1
    initial #2000 -> phase2_go;
`endif

    task apply(input integer vec);
        begin
            req = vec[7:0];
            #1;
            exp_idx = 3'd0;
            for (j = 0; j < 8; j = j + 1)
                if (req[j]) exp_idx = j[2:0];
            if (idx !== exp_idx || valid !== (req != 8'h00)) begin
                bad = bad + 1;
                if (bad <= 5)
                    $display("  vec %02h: idx=%0d valid=%0b, expected idx=%0d valid=%0b", req, idx, valid, exp_idx, req != 8'h00);
            end
        end
    endtask

    initial begin
        $display("tb_prio_enc8: exhaustive sweep, 256 vectors");
`ifdef DBG_PORT
        $dumpfile("prio_dbg.vcd");
        $dumpvars(0, tb_prio_enc8);
`endif
`ifdef SPLIT_PHASE
        for (v = 0; v < 128; v = v + 1) apply(v);
        $display("tb_prio_enc8: phase 1 done (128 vectors, %0d bad), waiting for phase 2 release", bad);
        @(phase2_go);
        for (v = 128; v < 256; v = v + 1) apply(v);
`else
        for (v = 0; v < 256; v = v + 1) apply(v);
`endif
        if (bad == 0) $display("PASS: tb_prio_enc8 (256/256 vectors)");
        else          $display("FAIL: tb_prio_enc8 (%0d/256 vectors wrong)", bad);
        $finish;
    end
endmodule
