// Full-throughput register slice.
module axis_pipe #(parameter W = 32) (
  input  wire         clk,
  input  wire         rstn,
  input  wire [W-1:0] s_data,
  input  wire         s_valid,
  output wire         s_ready,
  output reg  [W-1:0] m_data,
  output reg          m_valid,
  input  wire         m_ready
);
  assign s_ready = !m_valid || m_ready;
  always @(posedge clk) begin
    if (!rstn) m_valid <= 1'b0;
    else if (s_ready) begin
      m_valid <= s_valid;
      m_data  <= s_data;
    end
  end
endmodule
