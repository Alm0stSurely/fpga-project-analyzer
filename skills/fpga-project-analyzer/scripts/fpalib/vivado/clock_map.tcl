# fpa: after RTL elaboration, export each inferred register's clock source (exact through SV interfaces).
# Expects an elaborated design to be open (or run after rtl_netlist.tcl's elaboration).
# Output JSON: {"top": T, "regs": [[cell, clock_root_net, driver_pin], ...]}
proc js {s} { return "\"[string map {\\ \\\\ \" \\\" \n \\n \t \\t} $s]\"" }
proc fpa_clock_map {top out} {
  set fh [open $out w]
  puts $fh "\{\"top\":[js $top],\"regs\":\["
  set first 1
  set roots {}
  foreach c [get_cells -hierarchical -quiet -filter {REF_NAME =~ RTL_REG* || REF_NAME =~ RTL_LATCH* || REF_NAME =~ RTL_RAM* || REF_NAME =~ RTL_ROM*}] {
    set cp [lindex [get_pins -quiet -of_objects $c -filter {REF_PIN_NAME == C || REF_PIN_NAME == CLK || REF_PIN_NAME == G}] 0]
    if {$cp eq ""} { continue }
    set n [lindex [get_nets -quiet -of_objects $cp] 0]
    if {$n eq ""} { continue }
    set root [get_property NAME [lindex [get_nets -quiet -top_net_of_hierarchical_group -of_objects $cp] 0]]
    if {![dict exists $roots $root]} {
      set drv [lindex [get_pins -quiet -leaf -of_objects [get_nets -quiet -segments $n] -filter {DIRECTION == OUT}] 0]
      if {$drv eq ""} { set drv [lindex [get_ports -quiet -of_objects [get_nets -quiet -segments $n]] 0] }
      dict set roots $root [expr {$drv eq "" ? "" : [get_property NAME $drv]}]
    }
    puts -nonewline $fh [expr {$first ? "" : ","}]
    puts $fh "\[[js [get_property NAME $c]],[js $root],[js [dict get $roots $root]]\]"
    set first 0
  }
  puts $fh "\]\}"
  close $fh
  puts "FPA_CLOCKS=$out"
}
