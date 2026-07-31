# Fly Ball 批次写入报告

- 模式：已写入
- 队列总数：241
- 实际修改：123
- 重新剪辑并校时：115
- 仅校时或修改元数据：8
- 保持原样、等待后续处理：118
- 完整上下文复剪通过：85
- 部分上下文经画面复核后通过：30
- 千问提出但未自动写入的球路变化：3
- 独立击球短片复核通过：123
- 独立击球短片复核拒绝：97
- 拒绝原因包含无可见击球：97
- 拒绝原因包含无完整现场投球/挥棒：21
- 拒绝原因包含无球棒击球声：83
- 拒绝原因包含回放或慢动作：0

## 本次纠正说明

- 第一批上一次写入了 220 条；本次独立短片复核后保留 123 条。
- 97 条二次复核失败样本已完整恢复到第一批修改前的 `8e8a45d3` 版本，
  没有删除目录、创建空目录或保留部分修改。
- 第一轮未通过的 21 条继续保持原样，因此本批共有 118 条等待后续处理。
- 这 97 条不是永久报废，将进入源视频扩大范围、重新定位音频击球点的流程。
- 拒绝原因数量存在重叠：同一条可能同时没有可见击球、没有现场投球/挥棒，
  并且候选声音是解说或其他广播声音。
- 千问提出的 3 条球路变化没有自动写入，原球路字段已保留。

## 验证结果

- 批次集合核对：123 个二次通过目录正好等于相对 `8e8a45d3` 的修改目录。
- 二次拒绝目录仍有修改：0。
- 批次写入验证：241 条对账，错误 0。
- 全数据结构检查：1,207/1,207 通过。
- 全数据音视频可读性及音视频时长一致性检查：1,207/1,207 通过。

## 原始错误分类

- clip_too_short: 158
- contact_timestamp_wrong: 79
- semantic_or_schema_review: 2
- source_recovery_required: 2

## 已修改样本

| 样本 | 结果 | 修改前击球区间 | 修改后击球区间 | 原时长 | 新时长 | 球路 |
| --- | --- | --- | --- | ---: | ---: | --- |
| F_0001 | recut_and_retime | 0.940-1.040 | 0.925-1.025 | 7.014 | 12.995 | fly -> fly |
| F_0005 | recut_and_retime | 1.580-1.680 | 1.575-1.675 | 7.014 | 13.635 | fly -> fly |
| F_0006 | recut_and_retime | 0.790-0.890 | 0.785-0.885 | 7.014 | 12.845 | pop_fly -> pop_fly |
| F_0008 | recut_and_retime | 3.400-3.500 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0010 | recut_and_retime | 3.390-3.490 | 1.955-2.055 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0011 | recut_and_retime | 1.060-1.160 | 1.055-1.155 | 7.014 | 13.125 | fly -> fly |
| F_0012 | recut_and_retime | 3.370-3.470 | 1.965-2.065 | 7.015 | 14.000 | line_drive -> line_drive |
| F_0013 | recut_and_retime | 3.300-3.400 | 1.955-2.055 | 7.006 | 14.000 | pop_fly -> pop_fly |
| F_0014 | recut_and_retime | 1.090-1.190 | 1.085-1.185 | 7.014 | 13.155 | fly -> fly |
| F_0016 | recut_and_retime | 3.660-3.760 | 1.955-2.055 | 7.014 | 14.000 | line_drive -> line_drive |
| F_0018 | recut_and_retime | 1.920-2.020 | 1.905-2.005 | 7.014 | 9.059 | fly -> fly |
| F_0019 | recut_and_retime | 3.980-4.120 | 1.945-2.045 | 7.014 | 14.000 | line_drive -> line_drive |
| F_0022 | recut_and_retime | 3.440-3.540 | 1.955-2.055 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0025 | recut_and_retime | 0.960-1.060 | 0.945-1.045 | 7.014 | 13.015 | fly -> fly |
| F_0026 | recut_and_retime | 2.300-2.400 | 1.945-2.045 | 7.014 | 14.000 | fly -> fly |
| F_0027 | recut_and_retime | 0.590-0.690 | 0.685-0.785 | 7.014 | 12.755 | line_drive -> line_drive |
| F_0028 | recut_and_retime | 0.910-1.010 | 0.715-0.815 | 7.014 | 12.785 | fly -> fly |
| F_0034 | recut_and_retime | 3.230-3.330 | 1.945-2.045 | 7.014 | 14.000 | fly -> fly |
| F_0036 | recut_and_retime | 3.410-3.510 | 1.955-2.055 | 7.012 | 14.000 | line_drive -> line_drive |
| F_0037 | recut_and_retime | 1.600-1.700 | 1.585-1.685 | 7.014 | 13.655 | fly -> fly |
| F_0040 | recut_and_retime | 0.883-0.983 | 0.755-0.855 | 7.014 | 12.825 | pop_fly -> pop_fly |
| F_0041 | recut_and_retime | 3.390-3.490 | 1.955-2.055 | 7.006 | 10.426 | fly -> fly |
| F_0043 | recut_and_retime | 1.700-1.800 | 1.695-1.795 | 7.014 | 13.755 | pop_fly -> pop_fly |
| F_0044 | recut_and_retime | 3.330-3.430 | 1.965-2.065 | 7.006 | 14.000 | line_drive -> line_drive |
| F_0046 | recut_and_retime | 0.870-0.970 | 0.855-0.955 | 7.014 | 12.925 | fly -> fly |
| F_0047 | recut_and_retime | 3.400-3.500 | 1.955-2.055 | 7.013 | 14.000 | line_drive -> line_drive |
| F_0048 | retime_or_metadata_only | 2.820-2.920 | 2.015-2.115 | 7.014 | 7.014 | line_drive -> line_drive |
| F_0049 | recut_and_retime | 3.390-3.490 | 1.965-2.065 | 7.000 | 14.000 | line_drive -> line_drive |
| F_0051 | recut_and_retime | 3.400-3.500 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0052 | recut_and_retime | 1.780-1.880 | 1.765-1.865 | 7.014 | 13.835 | fly -> fly |
| F_0053 | retime_or_metadata_only | 2.100-2.180 | 1.955-2.055 | 7.014 | 7.014 | line_drive -> line_drive |
| F_0057 | recut_and_retime | 3.270-3.420 | 1.955-2.055 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0058 | recut_and_retime | 2.230-2.330 | 1.955-2.055 | 7.014 | 14.000 | fly -> fly |
| F_0060 | recut_and_retime | 3.380-3.420 | 1.945-2.045 | 7.007 | 8.692 | line_drive -> line_drive |
| F_0067 | recut_and_retime | 0.570-0.670 | 0.555-0.655 | 7.014 | 12.625 | line_drive -> line_drive |
| F_0068 | recut_and_retime | 3.600-3.700 | 1.945-2.045 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0069 | recut_and_retime | 4.120-4.220 | 1.955-2.055 | 7.000 | 11.277 | fly -> fly |
| F_0072 | recut_and_retime | 3.480-3.620 | 1.955-2.055 | 7.007 | 10.581 | fly -> fly |
| F_0073 | recut_and_retime | 1.030-1.130 | 1.015-1.115 | 7.014 | 13.085 | fly -> fly |
| F_0077 | recut_and_retime | 4.200-4.300 | 1.955-2.055 | 7.007 | 7.094 | line_drive -> line_drive |
| F_0082 | recut_and_retime | 4.020-4.120 | 2.445-2.545 | 7.006 | 13.934 | fly -> fly |
| F_0088 | retime_or_metadata_only | 1.480-1.620 | 1.495-1.595 | 7.014 | 7.014 | line_drive -> line_drive |
| F_0090 | recut_and_retime | 3.390-3.490 | 1.955-2.055 | 7.007 | 13.871 | line_drive -> line_drive |
| F_0091 | recut_and_retime | 2.160-2.260 | 1.955-2.055 | 7.014 | 14.000 | fly -> fly |
| F_0092 | recut_and_retime | 1.705-1.805 | 1.695-1.795 | 7.014 | 13.765 | pop_fly -> pop_fly |
| F_0094 | recut_and_retime | 1.370-1.470 | 1.365-1.465 | 7.014 | 12.729 | fly -> fly |
| F_0095 | recut_and_retime | 3.390-3.490 | 1.945-2.045 | 7.006 | 11.406 | pop_fly -> pop_fly |
| F_0099 | recut_and_retime | 3.226-3.326 | 1.945-2.045 | 7.006 | 14.000 | line_drive -> line_drive |
| F_0100 | recut_and_retime | 2.950-3.050 | 1.955-2.055 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0102 | retime_or_metadata_only | 2.560-2.660 | 2.675-2.775 | 7.014 | 7.014 | line_drive -> line_drive |
| F_0103 | recut_and_retime | 1.410-1.510 | 1.405-1.505 | 7.014 | 13.475 | fly -> fly |
| F_0105 | retime_or_metadata_only | 0.830-0.930 | 0.835-0.935 | 7.014 | 7.014 | line_drive -> line_drive |
| F_0106 | recut_and_retime | 1.780-1.820 | 1.785-1.885 | 7.014 | 13.845 | fly -> fly |
| F_0108 | recut_and_retime | 0.800-0.900 | 0.795-0.895 | 7.014 | 12.865 | fly -> fly |
| F_0109 | recut_and_retime | 5.060-5.160 | 1.965-2.065 | 7.006 | 12.322 | fly -> fly |
| F_0110 | recut_and_retime | 4.140-4.240 | 1.965-2.065 | 7.006 | 14.000 | fly -> fly |
| F_0112 | recut_and_retime | 1.320-1.420 | 1.315-1.415 | 7.014 | 13.375 | pop_fly -> pop_fly |
| F_0114 | recut_and_retime | 2.180-2.220 | 1.855-1.955 | 7.014 | 13.925 | fly -> fly |
| F_0116 | recut_and_retime | 0.900-1.000 | 0.895-0.995 | 7.014 | 12.955 | pop_fly -> pop_fly |
| F_0117 | recut_and_retime | 1.840-1.940 | 1.825-1.925 | 7.014 | 13.895 | fly -> fly |
| F_0120 | recut_and_retime | 3.860-3.960 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0121 | recut_and_retime | 1.380-1.480 | 1.385-1.485 | 7.007 | 13.435 | pop_fly -> pop_fly |
| F_0123 | recut_and_retime | 0.730-0.830 | 0.755-0.855 | 7.014 | 8.158 | fly -> fly |
| F_0124 | recut_and_retime | 2.670-2.770 | 1.945-2.045 | 7.014 | 14.000 | fly -> fly |
| F_0127 | recut_and_retime | 1.320-1.420 | 1.315-1.415 | 7.014 | 13.385 | fly -> fly |
| F_0131 | recut_and_retime | 1.040-1.150 | 2.385-2.485 | 7.007 | 14.000 | fly -> fly |
| F_0133 | recut_and_retime | 1.950-2.050 | 1.825-1.925 | 7.014 | 13.895 | fly -> fly |
| F_0143 | recut_and_retime | 1.800-2.000 | 1.785-1.885 | 7.014 | 13.845 | fly -> fly |
| F_0148 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0150 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0151 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0152 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0154 | retime_or_metadata_only | 0.450-0.650 | 0.795-0.895 | 7.006 | 7.006 | line_drive -> line_drive |
| F_0157 | recut_and_retime | 0.010-0.110 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0159 | retime_or_metadata_only | 0.800-0.950 | 1.595-1.695 | 7.007 | 7.007 | line_drive -> line_drive |
| F_0167 | recut_and_retime | 1.940-2.040 | 1.955-2.055 | 7.000 | 7.979 | fly -> fly |
| F_0168 | recut_and_retime | 0.170-0.270 | 1.705-1.805 | 7.006 | 13.775 | fly -> fly |
| F_0175 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0176 | recut_and_retime | 0.000-0.100 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0177 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.002 | 14.000 | fly -> fly |
| F_0179 | recut_and_retime | 2.800-3.000 | 1.955-2.055 | 7.006 | 6.185 | fly -> fly |
| F_0181 | recut_and_retime | 1.980-2.080 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0184 | recut_and_retime | 1.340-1.440 | 1.345-1.445 | 7.014 | 13.405 | fly -> fly |
| F_0189 | recut_and_retime | 0.000-0.100 | 1.765-1.865 | 7.006 | 10.060 | fly -> fly |
| F_0193 | recut_and_retime | 1.800-2.000 | 1.035-1.135 | 7.014 | 13.105 | fly -> fly |
| F_0194 | recut_and_retime | 0.660-0.760 | 0.645-0.745 | 7.014 | 12.715 | fly -> fly |
| F_0199 | recut_and_retime | 0.250-0.350 | 1.945-2.045 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0202 | recut_and_retime | 0.570-0.670 | 1.945-2.045 | 7.006 | 14.000 | line_drive -> line_drive |
| F_0211 | recut_and_retime | 0.330-0.430 | 0.955-1.055 | 7.006 | 13.015 | line_drive -> line_drive |
| F_0212 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.007 | 11.014 | fly -> fly |
| F_0213 | retime_or_metadata_only | 3.090-3.190 | 1.975-2.075 | 7.006 | 7.006 | line_drive -> line_drive |
| F_0217 | recut_and_retime | 0.800-0.900 | 1.355-1.455 | 7.007 | 13.415 | fly -> fly |
| F_0218 | recut_and_retime | 0.110-0.210 | 1.955-2.055 | 7.007 | 12.907 | fly -> fly |
| F_0221 | recut_and_retime | 1.340-1.440 | 1.325-1.425 | 7.014 | 13.395 | fly -> fly |
| F_0226 | recut_and_retime | 0.800-0.950 | 0.315-0.415 | 7.014 | 12.385 | fly -> fly |
| F_0228 | recut_and_retime | 1.080-1.180 | 1.075-1.175 | 7.014 | 13.145 | fly -> fly |
| F_0237 | recut_and_retime | 0.800-0.900 | 1.635-1.735 | 7.007 | 11.562 | line_drive -> line_drive |
| F_0239 | recut_and_retime | 0.630-0.730 | 0.935-1.035 | 7.006 | 13.005 | fly -> fly |
| F_0242 | recut_and_retime | 1.940-2.040 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0243 | recut_and_retime | 1.060-1.160 | 1.935-2.035 | 7.000 | 7.755 | fly -> fly |
| F_0246 | recut_and_retime | 0.190-0.290 | 1.945-2.045 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0249 | recut_and_retime | 1.640-1.740 | 1.635-1.735 | 7.014 | 13.695 | fly -> fly |
| F_0251 | recut_and_retime | 0.980-1.080 | 1.955-2.055 | 7.000 | 7.955 | pop_fly -> pop_fly |
| F_0255 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.006 | 9.943 | fly -> fly |
| F_0258 | recut_and_retime | 0.270-0.370 | 1.945-2.045 | 7.006 | 12.199 | fly -> fly |
| F_0269 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0270 | recut_and_retime | 0.270-0.370 | 1.715-1.815 | 7.007 | 13.785 | line_drive -> line_drive |
| F_0271 | recut_and_retime | 0.370-0.470 | 1.935-2.035 | 7.006 | 8.832 | line_drive -> line_drive |
| F_0273 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.006 | 8.785 | fly -> fly |
| F_0275 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.006 | 9.941 | fly -> fly |
| F_0277 | recut_and_retime | 0.510-0.610 | 1.915-2.015 | 7.006 | 9.726 | fly -> fly |
| F_0278 | recut_and_retime | 1.940-2.040 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0279 | recut_and_retime | 0.100-0.300 | 1.945-2.045 | 7.006 | 8.407 | line_drive -> line_drive |
| F_0283 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0284 | recut_and_retime | 1.560-1.660 | 1.555-1.655 | 5.488 | 13.615 | fly -> fly |
| F_0285 | recut_and_retime | 1.020-1.120 | 1.015-1.115 | 7.014 | 13.085 | fly -> fly |
| F_0288 | recut_and_retime | 1.970-2.070 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0290 | recut_and_retime | 1.670-1.770 | 1.665-1.765 | 7.014 | 13.735 | fly -> fly |
| F_0292 | recut_and_retime | 1.970-2.070 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0296 | recut_and_retime | 1.970-2.070 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0308 | recut_and_retime | 1.370-1.470 | 1.375-1.475 | 7.014 | 13.445 | fly -> fly |
| F_0309 | recut_and_retime | 1.950-2.050 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0316 | recut_and_retime | 1.950-2.050 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |

## 保持原样、等待后续处理的样本

| 样本 | 原始错误 | 当前原因 |
| --- | --- | --- |
| F_0002 | clip_too_short | contact_gate_reject |
| F_0004 | clip_too_short | contact_gate_reject |
| F_0029 | clip_too_short | contact_gate_reject |
| F_0030 | clip_too_short | contact_gate_reject |
| F_0032 | clip_too_short | contact_gate_reject |
| F_0035 | clip_too_short | contact_gate_reject |
| F_0061 | clip_too_short | contact_gate_reject |
| F_0064 | clip_too_short | contact_gate_reject |
| F_0070 | contact_timestamp_wrong | contact_gate_reject |
| F_0071 | contact_timestamp_wrong | contact_gate_reject |
| F_0075 | contact_timestamp_wrong | contact_gate_reject |
| F_0081 | contact_timestamp_wrong | contact_gate_reject |
| F_0083 | clip_too_short | contact_gate_reject |
| F_0085 | clip_too_short | no_candidate_selected |
| F_0087 | clip_too_short | contact_gate_reject |
| F_0107 | contact_timestamp_wrong | contact_gate_reject |
| F_0115 | clip_too_short | no_candidate_selected |
| F_0125 | clip_too_short | no_candidate_selected |
| F_0129 | contact_timestamp_wrong | contact_gate_reject |
| F_0130 | contact_timestamp_wrong | contact_gate_reject |
| F_0132 | clip_too_short | contact_gate_reject |
| F_0134 | clip_too_short | contact_gate_reject |
| F_0135 | contact_timestamp_wrong | contact_gate_reject |
| F_0136 | clip_too_short | contact_gate_reject |
| F_0138 | clip_too_short | contact_gate_reject |
| F_0139 | contact_timestamp_wrong | contact_gate_reject |
| F_0144 | contact_timestamp_wrong | contact_gate_reject |
| F_0146 | contact_timestamp_wrong | contact_gate_reject |
| F_0147 | clip_too_short | contact_gate_reject |
| F_0149 | clip_too_short | contact_gate_reject |
| F_0153 | contact_timestamp_wrong | contact_gate_reject |
| F_0155 | contact_timestamp_wrong | contact_gate_reject |
| F_0156 | contact_timestamp_wrong | contact_gate_reject |
| F_0158 | contact_timestamp_wrong | contact_gate_reject |
| F_0160 | contact_timestamp_wrong | contact_gate_reject |
| F_0161 | contact_timestamp_wrong | contact_gate_reject |
| F_0163 | contact_timestamp_wrong | contact_gate_reject |
| F_0165 | contact_timestamp_wrong | contact_gate_reject |
| F_0166 | contact_timestamp_wrong | contact_gate_reject |
| F_0169 | clip_too_short | contact_gate_reject |
| F_0171 | contact_timestamp_wrong | contact_gate_reject |
| F_0172 | contact_timestamp_wrong | contact_gate_reject |
| F_0173 | clip_too_short | contact_gate_reject |
| F_0174 | clip_too_short | contact_gate_reject |
| F_0180 | contact_timestamp_wrong | contact_gate_reject |
| F_0182 | contact_timestamp_wrong | contact_gate_reject |
| F_0183 | contact_timestamp_wrong | contact_gate_reject |
| F_0185 | contact_timestamp_wrong | contact_gate_reject |
| F_0186 | contact_timestamp_wrong | contact_gate_reject |
| F_0187 | clip_too_short | contact_gate_reject |
| F_0191 | contact_timestamp_wrong | contact_gate_reject |
| F_0195 | contact_timestamp_wrong | contact_gate_reject |
| F_0196 | clip_too_short | contact_gate_reject |
| F_0198 | contact_timestamp_wrong | contact_gate_reject |
| F_0200 | contact_timestamp_wrong | contact_gate_reject |
| F_0201 | contact_timestamp_wrong | contact_gate_reject |
| F_0205 | contact_timestamp_wrong | contact_gate_reject |
| F_0208 | contact_timestamp_wrong | contact_gate_reject |
| F_0210 | clip_too_short | contact_gate_reject |
| F_0219 | clip_too_short | contact_gate_reject |
| F_0223 | contact_timestamp_wrong | contact_gate_reject |
| F_0224 | clip_too_short | contact_gate_reject |
| F_0225 | contact_timestamp_wrong | contact_gate_reject |
| F_0227 | contact_timestamp_wrong | contact_gate_reject |
| F_0229 | clip_too_short | no_candidate_selected |
| F_0230 | clip_too_short | contact_gate_reject |
| F_0231 | contact_timestamp_wrong | contact_gate_reject |
| F_0232 | contact_timestamp_wrong | no_candidate_selected |
| F_0234 | clip_too_short | contact_gate_reject |
| F_0235 | contact_timestamp_wrong | contact_gate_reject |
| F_0236 | clip_too_short | contact_gate_reject |
| F_0238 | clip_too_short | contact_gate_reject |
| F_0241 | contact_timestamp_wrong | contact_gate_reject |
| F_0244 | clip_too_short | no_candidate_selected |
| F_0248 | clip_too_short | contact_gate_reject |
| F_0250 | clip_too_short | contact_gate_reject |
| F_0252 | clip_too_short | no_candidate_selected |
| F_0254 | contact_timestamp_wrong | contact_gate_reject |
| F_0257 | clip_too_short | contact_gate_reject |
| F_0260 | clip_too_short | contact_gate_reject |
| F_0261 | clip_too_short | contact_gate_reject |
| F_0264 | contact_timestamp_wrong | contact_gate_reject |
| F_0265 | contact_timestamp_wrong | contact_gate_reject |
| F_0267 | clip_too_short | contact_gate_reject |
| F_0268 | clip_too_short | contact_gate_reject |
| F_0281 | contact_timestamp_wrong | contact_gate_reject |
| F_0286 | clip_too_short | contact_gate_reject |
| F_0287 | contact_timestamp_wrong | contact_gate_reject |
| F_0289 | clip_too_short | contact_gate_reject |
| F_0291 | clip_too_short | contact_gate_reject |
| F_0293 | clip_too_short | contact_gate_reject |
| F_0294 | clip_too_short | contact_gate_reject |
| F_0295 | clip_too_short | no_candidate_selected |
| F_0297 | clip_too_short | contact_gate_reject |
| F_0298 | clip_too_short | contact_gate_reject |
| F_0299 | clip_too_short | no_candidate_selected |
| F_0300 | clip_too_short | no_candidate_selected |
| F_0301 | clip_too_short | no_candidate_selected |
| F_0303 | clip_too_short | no_candidate_selected |
| F_0305 | contact_timestamp_wrong | contact_gate_reject |
| F_0306 | clip_too_short | contact_gate_reject |
| F_0307 | contact_timestamp_wrong | contact_gate_reject |
| F_0310 | clip_too_short | contact_gate_reject |
| F_0312 | clip_too_short | contact_gate_reject |
| F_0313 | clip_too_short | no_candidate_selected |
| F_0314 | clip_too_short | no_candidate_selected |
| F_0315 | contact_timestamp_wrong | contact_gate_reject |
| F_0318 | clip_too_short | contact_gate_reject |
| F_0319 | source_recovery_required | contact_gate_reject |
| F_0320 | contact_timestamp_wrong | no_candidate_selected |
| F_0322 | contact_timestamp_wrong | no_candidate_selected |
| F_0323 | contact_timestamp_wrong | no_candidate_selected |
| F_0324 | source_recovery_required | no_candidate_selected |
| F_0325 | clip_too_short | contact_gate_reject |
| F_0326 | contact_timestamp_wrong | no_candidate_selected |
| F_0328 | contact_timestamp_wrong | contact_gate_reject |
| F_0330 | contact_timestamp_wrong | no_candidate_selected |
| F_0331 | contact_timestamp_wrong | audio_visual_time_mismatch |
