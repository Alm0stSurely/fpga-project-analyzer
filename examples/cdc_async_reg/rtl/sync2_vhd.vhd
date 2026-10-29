-- Two separate flops, ASYNC_REG set with a VHDL attribute.
library ieee;
use ieee.std_logic_1164.all;

entity sync2_vhd is
  port (clk : in std_logic; d : in std_logic; q : out std_logic);
end entity;

architecture rtl of sync2_vhd is
  signal ff1, ff2 : std_logic := '0';
  attribute ASYNC_REG : string;
  attribute ASYNC_REG of ff1, ff2 : signal is "TRUE";
begin
  process (clk)
  begin
    if rising_edge(clk) then
      ff1 <= d;
      ff2 <= ff1;
    end if;
  end process;
  q <= ff2;
end architecture;
