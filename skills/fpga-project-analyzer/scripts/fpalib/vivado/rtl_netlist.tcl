# fpa: elaborate RTL (synth_design -rtl) and dump the hierarchical netlist as JSON.
# vivado -mode batch -source rtl_netlist.tcl -tclargs <xpr|filelist> <top> <part> <out.json> <max_cells>
lassign $argv src top part out maxcells
if {[string match *.xpr $src]} {
  open_project $src
  set ok [catch {synth_design -rtl -rtl_skip_mlo -top $top -name fpa_rtl} err]
  if {$ok} { synth_design -rtl -top $top -name fpa_rtl }
} else {
  create_project -in_memory -part $part
  set fh [open $src]
  foreach f [split [read $fh] "\n"] {
    if {$f eq ""} { continue }
    set e [string tolower [file extension $f]]
    if {$e eq ".vhd" || $e eq ".vhdl"} { read_vhdl $f } elseif {$e eq ".sv"} { read_verilog -sv $f } else { read_verilog $f }
  }
  close $fh
  set ok [catch {synth_design -rtl -rtl_skip_mlo -top $top -part $part -name fpa_rtl} err]
  if {$ok} { synth_design -rtl -top $top -part $part -name fpa_rtl }
}
proc js {s} { return "\"[string map {\\ \\\\ \" \\\" \n \\n \t \\t} $s]\"" }
proc netname {n} { if {$n eq ""} { return "" }; return [get_property NAME $n] }
set fh [open $out w]
puts $fh "\{\"top\":[js $top],\"ports\":\["
set first 1
foreach p [get_ports -quiet] {
  set n [netname [lindex [get_nets -quiet -of_objects $p] 0]]
  puts -nonewline $fh [expr {$first ? "" : ","}][list]
  puts $fh "\[[js [get_property NAME $p]],[js [get_property DIRECTION $p]],[js $n]\]"
  set first 0
}
puts $fh "\],\"cells\":\["
set cells [get_cells -hierarchical -quiet]
set truncated 0
if {[llength $cells] > $maxcells} { set cells [lrange $cells 0 [expr {$maxcells - 1}]]; set truncated 1 }
set first 1
foreach c $cells {
  set name [get_property NAME $c]
  set prim [get_property IS_PRIMITIVE $c]
  set pins {}
  foreach p [get_pins -quiet -of_objects $c] {
    set up [netname [lindex [get_nets -quiet -of_objects $p -boundary_type upper] 0]]
    set lo ""
    if {!$prim} { set lo [netname [lindex [get_nets -quiet -of_objects $p -boundary_type lower] 0]] }
    lappend pins "\[[js [get_property REF_PIN_NAME $p]],[js [get_property DIRECTION $p]],[js $up],[js $lo]\]"
  }
  puts -nonewline $fh [expr {$first ? "" : ","}]
  puts $fh "\{\"n\":[js $name],\"ref\":[js [get_property REF_NAME $c]],\"prim\":$prim,\"pins\":\[[join $pins ,]\]\}"
  set first 0
}
puts $fh "\],\"truncated\":$truncated\}"
close $fh
puts "FPA_NETLIST=$out"
