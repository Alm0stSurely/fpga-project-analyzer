# fpa: produce exact .bd + .hwh from a BD Tcl script or an existing .xpr.
# vivado -mode batch -source export_bd.tcl -tclargs <bdtcl|xpr> <outdir> <part> [rtl_list_file]
lassign $argv src out part rtllist
file mkdir $out
if {[string match *.xpr $src]} {
  open_project $src
} else {
  create_project fpa_tmp $out/proj -part $part -force
  if {$rtllist ne "" && [file exists $rtllist]} {
    set fh [open $rtllist]
    foreach f [split [read $fh] "\n"] { if {$f ne "" && [file exists $f]} { add_files -norecurse $f } }
    close $fh
    update_compile_order -fileset sources_1
  }
  set fh [open $src]; set txt [read $fh]; close $fh
  # generated scripts refuse other Vivado versions and pin IP versions
  regsub -all {set scripts_vivado_version [^\n]+} $txt "set scripts_vivado_version [version -short]" txt
  regsub -all {set bCheckIPs 1} $txt {set bCheckIPs 0} txt
  regsub -all {set bCheckModules 1} $txt {set bCheckModules 0} txt
  regsub -all {(-vlnv[ \t]+[A-Za-z0-9_.]+:ip:[A-Za-z0-9_]+):[0-9.]+} $txt {\1} txt
  set fh [open $out/patched_bd.tcl w]; puts $fh $txt; close $fh
  if {[catch {source $out/patched_bd.tcl} err]} { puts "FPA_WARN source: $err" }
}
foreach bd [get_files -quiet *.bd] {
  if {[catch {open_bd_design $bd} err]} { puts "FPA_WARN open: $err" }
}
set n 0
foreach d [get_bd_designs -quiet] {
  current_bd_design $d
  catch {save_bd_design}
  set f [lindex [get_files -quiet [get_property NAME $d].bd] 0]
  if {$f eq ""} { continue }
  if {[catch {generate_target {synthesis} $f} err]} { puts "FPA_WARN generate: $err" }
  set hwh [lindex [glob -nocomplain [file dirname $f]/hw_handoff/*.hwh [file dirname [file dirname [file dirname [file dirname $f]]]]/../*.gen/sources_1/bd/[get_property NAME $d]/hw_handoff/*.hwh] 0]
  if {$hwh eq ""} {
    set hwh [lindex [glob -nocomplain -directory [get_property DIRECTORY [current_project]] -types f */sources_1/bd/[get_property NAME $d]/hw_handoff/*.hwh] 0]
  }
  file copy -force $f $out/[get_property NAME $d].bd
  puts "FPA_BD=$out/[get_property NAME $d].bd"
  if {$hwh ne ""} {
    file copy -force $hwh $out/[get_property NAME $d].hwh
    puts "FPA_HWH=$out/[get_property NAME $d].hwh"
  }
  incr n
}
if {$n == 0} { puts "FPA_ERROR no block design created" }
