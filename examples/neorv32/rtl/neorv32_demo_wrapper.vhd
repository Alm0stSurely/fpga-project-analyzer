-- ================================================================================ --
-- NEORV32 demo - VHDL->Verilog conversion wrapper                                  --
-- -------------------------------------------------------------------------------- --
-- Pure mirror of rtl/test_setups/neorv32_test_setup_bootloader.vhd (NEORV32 v1.13.7)--
-- The upstream test-setup entity is instantiated UNMODIFIED (compiled from the     --
-- pristine source file), so the simulated SoC is by construction the same SoC the  --
-- fpa diagram shows: rv32imc + Zicntr, IMEM 16 KiB, DMEM 8 KiB, 8 GPIO outputs,    --
-- CLINT, UART0, BOOT_MODE_SELECT = 0 (internal bootloader).                        --
--                                                                                  --
-- Only CLOCK_FREQUENCY is overridden. It does not change any hardware: it is only  --
-- the reset value of SYSINFO.CLK, which the bootloader reads to derive the UART0   --
-- baud divisor (19200 baud), the status-LED blink period (CLK/4) and the auto-boot --
-- timeout (8 * CLK mtime ticks). A small value keeps those at sane wall-clock      --
-- durations at simulator speeds (rationale: see build.sh).                         --
--                                                                                  --
-- No extra ports: activity probes are read directly from internal netlist signals  --
-- via Verilator public_flat_rd (probes.vlt), so this wrapper stays a pure mirror.  --
-- ================================================================================ --

library ieee;
use ieee.std_logic_1164.all;

library neorv32;

entity neorv32_demo_wrapper is
  generic (
    CLOCK_FREQUENCY : natural := 1_000_000 -- "virtual" clk_i frequency in Hz (see header)
  );
  port (
    -- Global control --
    clk_i       : in  std_ulogic; -- global clock, rising edge
    rstn_i      : in  std_ulogic; -- global reset, low-active, async
    -- GPIO --
    gpio_o      : out std_ulogic_vector(7 downto 0); -- parallel output
    -- UART0 --
    uart0_txd_o : out std_ulogic; -- UART0 send data
    uart0_rxd_i : in  std_ulogic  -- UART0 receive data
  );
end entity;

architecture neorv32_demo_wrapper_rtl of neorv32_demo_wrapper is
begin

  test_setup_inst: entity neorv32.neorv32_test_setup_bootloader
  generic map (
    CLOCK_FREQUENCY => CLOCK_FREQUENCY,
    IMEM_SIZE       => 16*1024, -- = upstream default
    DMEM_SIZE       => 8*1024   -- = upstream default
  )
  port map (
    clk_i       => clk_i,
    rstn_i      => rstn_i,
    gpio_o      => gpio_o,
    uart0_txd_o => uart0_txd_o,
    uart0_rxd_i => uart0_rxd_i
  );

end architecture;
