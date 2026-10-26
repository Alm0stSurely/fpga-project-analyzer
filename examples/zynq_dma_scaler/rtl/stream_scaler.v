// AXI-Stream gain stage: y = sat(x * gain). Gain is configured from a slow clock.
module stream_scaler #(
  parameter DATA_W = 32
) (
  input  wire              aclk,
  input  wire              aresetn,
  input  wire              cfg_clk,
  input  wire [15:0]       gain_cfg,
  input  wire [DATA_W-1:0] s_axis_tdata,
  input  wire              s_axis_tvalid,
  output wire              s_axis_tready,
  input  wire              s_axis_tlast,
  output wire [DATA_W-1:0] m_axis_tdata,
  output wire              m_axis_tvalid,
  input  wire              m_axis_tready,
  output wire              m_axis_tlast
);
  reg  [15:0] gain_q;
  always @(posedge cfg_clk) gain_q <= gain_cfg;   // config register in cfg_clk domain

  wire [DATA_W-1:0] in_data, mul_data;
  wire              in_valid, in_ready, in_last;

  axis_pipe #(.W(DATA_W + 1)) u_in_pipe (
    .clk(aclk), .rstn(aresetn),
    .s_data({s_axis_tlast, s_axis_tdata}), .s_valid(s_axis_tvalid), .s_ready(s_axis_tready),
    .m_data({in_last, in_data}),           .m_valid(in_valid),      .m_ready(in_ready)
  );

  sat_mul #(.W(DATA_W)) u_mul (
    .clk(aclk), .a(in_data), .g(gain_q), .y(mul_data)
  );

  axis_pipe #(.W(DATA_W + 1)) u_out_pipe (
    .clk(aclk), .rstn(aresetn),
    .s_data({in_last, mul_data}), .s_valid(in_valid), .s_ready(in_ready),
    .m_data({m_axis_tlast, m_axis_tdata}), .m_valid(m_axis_tvalid), .m_ready(m_axis_tready)
  );
endmodule
