# fpa: run the analysis reports on a checkpoint or a project run.
# vivado -mode batch -source reports.tcl -tclargs <dcp|xpr> <outdir> [run]
lassign $argv src out run
file mkdir $out
if {[string match *.xpr $src]} {
  open_project $src
  if {$run eq ""} { set run impl_1 }
  open_run $run
} else {
  open_checkpoint $src
}
report_timing_summary -max_paths 10 -report_unconstrained -file $out/timing_summary.rpt
report_clock_interaction -file $out/clock_interaction.rpt
catch {report_cdc -details -file $out/cdc.rpt}
catch {report_methodology -file $out/methodology.rpt}
report_drc -file $out/drc.rpt
report_utilization -file $out/utilization.rpt
puts "FPA_REPORTS=$out"
