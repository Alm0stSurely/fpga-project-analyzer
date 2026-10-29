// Stubs for Linux-only libc symbols referenced by the Verilator 5.052 runtime.
//
// Emscripten's musl headers define CPU_ZERO (via _GNU_SOURCE), so verilatedos_c.h
// (VlOs::getProcessAvailableParallelism) and verilated_threads.cpp
// (VlThreadPool::numaAssign) take their "Linux-like pthreads" branches, but
// Emscripten's libc does not implement these three functions -> wasm-ld reports
// "undefined symbol". They are only used for NUMA/affinity tuning of the worker
// thread pool, which a --threads 1 model never creates. Returning "not supported"
// makes Verilator fall back to its "Cannot determine" paths.
#ifdef __EMSCRIPTEN__
#include <errno.h>
#include <pthread.h>
#include <sched.h>

extern "C" {
int pthread_getaffinity_np(pthread_t, size_t, cpu_set_t*) { return ENOSYS; }
int pthread_setaffinity_np(pthread_t, size_t, const cpu_set_t*) { return ENOSYS; }
int sched_getcpu(void) { return 0; }
}
#endif
