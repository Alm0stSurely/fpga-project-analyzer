// Four 2-FF synchronizers on a clk_a -> clk_b crossing; only u_plain lacks ASYNC_REG.
module top (
  input  wire clk_a,
  input  wire clk_b,
  input  wire btn,
  output wire [3:0] led
);
  reg flag_a = 1'b0;
  always @(posedge clk_a) flag_a <= btn;

  sync2      u_plain (.clk(clk_b), .d(flag_a), .q(led[0]));  // missing ASYNC_REG -> finding
  sync2_attr u_attr  (.clk(clk_b), .d(flag_a), .q(led[1]));  // ASYNC_REG in RTL
  sync2      u_xdc   (.clk(clk_b), .d(flag_a), .q(led[2]));  // ASYNC_REG set in top.xdc
  sync2_vhd  u_vhd   (.clk(clk_b), .d(flag_a), .q(led[3]));  // VHDL, separate flops, attribute
endmodule

module sync2 (input wire clk, input wire d, output wire q);
  reg [1:0] s_reg = 2'b00;
  always @(posedge clk) s_reg <= {s_reg[0], d};
  assign q = s_reg[1];
endmodule

module sync2_attr (input wire clk, input wire d, output wire q);
  (* ASYNC_REG = "TRUE" *) reg [1:0] s_reg = 2'b00;
  always @(posedge clk) s_reg <= {s_reg[0], d};
  assign q = s_reg[1];
endmodule
