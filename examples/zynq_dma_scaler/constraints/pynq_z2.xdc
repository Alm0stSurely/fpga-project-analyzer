## PYNQ-Z2 user LEDs (LD0..LD3)
set_property -dict { PACKAGE_PIN R14 IOSTANDARD LVCMOS33 } [get_ports { gpio_rtl_0_tri_o[0] }]
set_property -dict { PACKAGE_PIN P14 IOSTANDARD LVCMOS33 } [get_ports { gpio_rtl_0_tri_o[1] }]
set_property -dict { PACKAGE_PIN N16 IOSTANDARD LVCMOS33 } [get_ports { gpio_rtl_0_tri_o[2] }]
