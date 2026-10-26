-- Registered unsigned multiply by Q8.8 gain with saturation.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity sat_mul is
  generic (W : positive := 32);
  port (
    clk : in  std_logic;
    a   : in  std_logic_vector(W-1 downto 0);
    g   : in  std_logic_vector(15 downto 0);
    y   : out std_logic_vector(W-1 downto 0)
  );
end entity sat_mul;

architecture rtl of sat_mul is
  signal p : unsigned(W+15 downto 0);
begin
  p <= unsigned(a) * unsigned(g);
  process (clk)
  begin
    if rising_edge(clk) then
      if p(W+15 downto W+8) /= 0 then
        y <= (others => '1');
      else
        y <= std_logic_vector(p(W+7 downto 8));
      end if;
    end if;
  end process;
end architecture rtl;
