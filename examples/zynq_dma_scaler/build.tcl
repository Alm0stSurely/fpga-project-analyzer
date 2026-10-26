# Demo design: PYNQ-Z2 class Zynq-7000. PS7 -> AXI DMA -> stream_scaler (RTL module ref) -> DMA.
# Usage: vivado -mode batch -source build.tcl [-tclargs impl]
set root [file normalize [file dirname [info script]]]
create_project demo $root/vivado -part xc7z020clg400-1 -force
add_files [glob $root/rtl/*.v $root/rtl/*.vhd]
add_files -fileset constrs_1 $root/constraints/pynq_z2.xdc
update_compile_order -fileset sources_1
create_bd_design design_1

set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 processing_system7_0]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} $ps
set_property -dict [list CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_USE_FABRIC_INTERRUPT {1} CONFIG.PCW_IRQ_F2P_INTR {1} \
  CONFIG.PCW_EN_CLK1_PORT {1} CONFIG.PCW_FPGA1_PERIPHERAL_FREQMHZ {50} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}] $ps

set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma axi_dma_0]
set_property -dict [list CONFIG.c_include_sg {0} CONFIG.c_sg_include_stscntrl_strm {0} CONFIG.c_sg_length_width {23}] $dma
set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio axi_gpio_0]
set_property -dict [list CONFIG.C_GPIO_WIDTH {4} CONFIG.C_ALL_OUTPUTS {1} CONFIG.C_IS_DUAL {1} CONFIG.C_GPIO2_WIDTH {16} CONFIG.C_ALL_OUTPUTS_2 {1} CONFIG.C_INTERRUPT_PRESENT {1}] $gpio

set clk {/processing_system7_0/FCLK_CLK0 (100 MHz)}
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list Clk_master $clk Clk_slave {Auto} Clk_xbar {Auto} Master {/processing_system7_0/M_AXI_GP0} Slave {/axi_dma_0/S_AXI_LITE} intc_ip {New AXI Interconnect} master_apm {0}] [get_bd_intf_pins axi_dma_0/S_AXI_LITE]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list Clk_master $clk Clk_slave {Auto} Clk_xbar {Auto} Master {/processing_system7_0/M_AXI_GP0} Slave {/axi_gpio_0/S_AXI} intc_ip {/ps7_0_axi_periph} master_apm {0}] [get_bd_intf_pins axi_gpio_0/S_AXI]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list Clk_master {Auto} Clk_slave $clk Clk_xbar {Auto} Master {/axi_dma_0/M_AXI_MM2S} Slave {/processing_system7_0/S_AXI_HP0} intc_ip {Auto} master_apm {0}] [get_bd_intf_pins processing_system7_0/S_AXI_HP0]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list Clk_master {Auto} Clk_slave $clk Clk_xbar {Auto} Master {/axi_dma_0/M_AXI_S2MM} Slave {/processing_system7_0/S_AXI_HP0} intc_ip {Auto} master_apm {0}] [get_bd_intf_pins axi_dma_0/M_AXI_S2MM]
make_bd_intf_pins_external [get_bd_intf_pins axi_gpio_0/GPIO]
set_property name gpio_rtl_0 [get_bd_intf_ports GPIO_0]

create_bd_cell -type hier stream_proc
create_bd_cell -type module -reference stream_scaler stream_proc/stream_scaler_0
create_bd_pin -dir I stream_proc/aclk
create_bd_pin -dir I stream_proc/aresetn
create_bd_pin -dir I stream_proc/cfg_clk
create_bd_pin -dir I -from 15 -to 0 stream_proc/gain
create_bd_intf_pin -mode Slave  -vlnv xilinx.com:interface:axis_rtl:1.0 stream_proc/S_AXIS
create_bd_intf_pin -mode Master -vlnv xilinx.com:interface:axis_rtl:1.0 stream_proc/M_AXIS
connect_bd_net [get_bd_pins stream_proc/aclk]    [get_bd_pins stream_proc/stream_scaler_0/aclk]
connect_bd_net [get_bd_pins stream_proc/aresetn] [get_bd_pins stream_proc/stream_scaler_0/aresetn]
connect_bd_net [get_bd_pins stream_proc/cfg_clk] [get_bd_pins stream_proc/stream_scaler_0/cfg_clk]
connect_bd_net [get_bd_pins stream_proc/gain]    [get_bd_pins stream_proc/stream_scaler_0/gain_cfg]
connect_bd_intf_net [get_bd_intf_pins stream_proc/S_AXIS] [get_bd_intf_pins stream_proc/stream_scaler_0/s_axis]
connect_bd_intf_net [get_bd_intf_pins stream_proc/M_AXIS] [get_bd_intf_pins stream_proc/stream_scaler_0/m_axis]

connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXIS_MM2S] [get_bd_intf_pins stream_proc/S_AXIS]
connect_bd_intf_net [get_bd_intf_pins stream_proc/M_AXIS] [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins stream_proc/aclk]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK1] [get_bd_pins stream_proc/cfg_clk]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] [get_bd_pins stream_proc/aresetn]
connect_bd_net [get_bd_pins axi_gpio_0/gpio2_io_o] [get_bd_pins stream_proc/gain]

# DMA interrupts -> PS (GPIO interrupt left unconnected)
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat xlconcat_0
set_property CONFIG.NUM_PORTS {2} [get_bd_cells xlconcat_0]
connect_bd_net [get_bd_pins axi_dma_0/mm2s_introut] [get_bd_pins xlconcat_0/In0]
connect_bd_net [get_bd_pins axi_dma_0/s2mm_introut] [get_bd_pins xlconcat_0/In1]
connect_bd_net [get_bd_pins xlconcat_0/dout] [get_bd_pins processing_system7_0/IRQ_F2P]

assign_bd_address
validate_bd_design
save_bd_design
generate_target all [get_files design_1.bd]
make_wrapper -files [get_files design_1.bd] -top -import
set_property top design_1_wrapper [current_fileset]
update_compile_order -fileset sources_1

# Static copies so the analyzer works without Vivado
file mkdir $root/bd
write_bd_tcl -force $root/bd/design_1_bd.tcl
file copy -force [get_files design_1.bd] $root/bd/design_1.bd
file copy -force [lindex [glob $root/vivado/demo.gen/sources_1/bd/design_1/hw_handoff/*.hwh] 0] $root/bd/design_1.hwh

if {[lsearch $argv impl] >= 0} {
  launch_runs impl_1 -to_step write_bitstream -jobs 8
  wait_on_run impl_1
  puts "IMPL_STATUS=[get_property STATUS [get_runs impl_1]]"
}
