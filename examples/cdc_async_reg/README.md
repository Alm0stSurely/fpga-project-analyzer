# cdc_async_reg

Four 1-bit synchronizers on a `clk_a` (100 MHz) → `clk_b` (125 MHz) crossing, in the common styles: a Verilog shift
register, the same with an `ASYNC_REG` attribute, the same constrained in XDC, and a VHDL process with two flops and
an attribute. Only `u_plain` lacks `ASYNC_REG`.

```bash
fpa build . && fpa findings .
```

```
M cdc-async-reg  /u_plain/s_reg_reg  Synchronizer without ASYNC_REG clk_a → clk_b
i cdc-sync       /u_attr/s_reg_reg   2-FF synchronizer clk_a → clk_b   (ASYNC_REG set in rtl)
i cdc-sync       /u_xdc/s_reg_reg    2-FF synchronizer clk_a → clk_b   (ASYNC_REG set in xdc)
i cdc-sync       /u_vhd/ff1_reg      2-FF synchronizer clk_a → clk_b   (ASYNC_REG set in rtl)
```
