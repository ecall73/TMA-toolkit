# TMA Report

- Spec: `/nfs/home/lizhiheng/xsai-env/tools/TMA-toolkit/presets/cute/default.yaml`
- Log: `/nfs/home/lizhiheng/xsai-env/tools/TMA-toolkit/examples/emu-error.default.log`
- Consistency: 7/8 passed
- Chart: `/nfs/home/lizhiheng/xsai-env/tools/TMA-toolkit/examples/tma-cute_combined.png`
- CSV: `/nfs/home/lizhiheng/xsai-env/tools/TMA-toolkit/examples/tma-cute_values.csv`
- Consistency JSON: `/nfs/home/lizhiheng/xsai-env/tools/TMA-toolkit/examples/tma-cute_consistency.json`

## Key Values

- `CUTE_L0_TC_HeadValidSlot` = `83723.0`
- `CUTE_L0_TC_IssueFire` = `91.0`
- `CUTE_L0_TC_Stall` = `83632.0`
- `CUTE_L1_TC_Stall_Memory` = `36537.0`
- `CUTE_L1_TC_Stall_Compute` = `521.0`
- `CUTE_L1_TC_Stall_Dependency` = `46574.0`

## Consistency Checks

| Name | Result | Detail |
|---|---|---|
| l1_sum_eq_l0_stall | PASS | lhs=83632.0 rhs=83632.0 diff=0.0 tol=0.0 |
| l2_sum_eq_l1_dependency | FAIL | lhs=73327.0 rhs=46574.0 diff=26753.0 tol=0.0 |
| aml_block_need_gated | PASS | expr=CUTE_L1_TC_Block_AML <= CUTE_L1_TC_Need_AML |
| bml_block_need_gated | PASS | expr=CUTE_L1_TC_Block_BML <= CUTE_L1_TC_Need_BML |
| cml_block_need_gated | PASS | expr=CUTE_L1_TC_Block_CML <= CUTE_L1_TC_Need_CML |
| adc_block_need_gated | PASS | expr=CUTE_L1_TC_Block_ADC <= CUTE_L1_TC_Need_ADC |
| bdc_block_need_gated | PASS | expr=CUTE_L1_TC_Block_BDC <= CUTE_L1_TC_Need_BDC |
| cdc_block_need_gated | PASS | expr=CUTE_L1_TC_Block_CDC <= CUTE_L1_TC_Need_CDC |
