// Fixed-priority arbiter: req[0] has the highest priority; the registered grant is one-hot or zero.
// Opt-in defects: ARB_COMPAT_MODE grants the highest-numbered requester instead,
// ARB_LOCK_TOP also raises the top grant bit whenever the top requester is active.
module prio_arbiter #(parameter N = 4) (
    input              clk,
    input              rst_n,
    input      [N-1:0] req,
    output reg [N-1:0] gnt
);
    integer i;
    reg [N-1:0] pick;

    always @* begin
        pick = {N{1'b0}};
`ifdef ARB_COMPAT_MODE
        for (i = 0; i < N; i = i + 1)
            if (req[i]) pick = 1 << i;
`else
        for (i = N - 1; i >= 0; i = i - 1)
            if (req[i]) pick = 1 << i;
`endif
`ifdef ARB_LOCK_TOP
        pick[N-1] = pick[N-1] | req[N-1];
`endif
    end

    always @(posedge clk or negedge rst_n)
        if (!rst_n) gnt <= {N{1'b0}};
        else        gnt <= pick;
endmodule
