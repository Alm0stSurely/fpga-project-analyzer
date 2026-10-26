/* Bare-metal loopback through the stream scaler. */
#include "xparameters.h"
#include "xaxidma.h"
#include "xgpio.h"

#define N 256
static u32 src[N] __attribute__((aligned(64)));
static u32 dst[N] __attribute__((aligned(64)));

int main(void)
{
    XAxiDma dma;
    XGpio gpio;
    XAxiDma_Config *cfg = XAxiDma_LookupConfig(XPAR_AXI_DMA_0_BASEADDR);
    XAxiDma_CfgInitialize(&dma, cfg);
    XGpio_Initialize(&gpio, XPAR_AXI_GPIO_0_BASEADDR);
    XGpio_DiscreteWrite(&gpio, 2, 0x0200);          /* gain = 2.0 (Q8.8) */

    for (int i = 0; i < N; i++) src[i] = i;
    Xil_DCacheFlushRange((UINTPTR)src, sizeof(src));
    XAxiDma_SimpleTransfer(&dma, (UINTPTR)dst, sizeof(dst), XAXIDMA_DEVICE_TO_DMA);
    XAxiDma_SimpleTransfer(&dma, (UINTPTR)src, sizeof(src), XAXIDMA_DMA_TO_DEVICE);
    while (XAxiDma_Busy(&dma, XAXIDMA_DEVICE_TO_DMA)) ;
    Xil_DCacheInvalidateRange((UINTPTR)dst, sizeof(dst));
    return dst[1] == 2 ? 0 : 1;
}
