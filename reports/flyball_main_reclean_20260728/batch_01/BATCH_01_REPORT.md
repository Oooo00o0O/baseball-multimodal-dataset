# Fly Ball 第一批重新清洗报告

数据提交：`c8a2863e`（`Reclean fly ball batch 1 with audio-bound timing`）

## 批次结果

- main 修复队列：241 条
- 实际修改：220 条
- 回源加长视频并重新标注击球时间：206 条
- 只修改击球时间或元数据：14 条
- 保持原样、进入后续源视频恢复：21 条
- 达到数值上下文门槛的长视频：153 条
- 未达到优选秒数但经视频确认完整过程可见：53 条
- 轨迹类型修正：5 条

Qwen 对 241 条全部完成复核：220 条通过本地音频候选、视频接触时间、现场击球、非回放和完整过程门槛；21 条未通过。未通过样本没有被删除、清空或覆盖。

## 原始首要错误

- 视频过短：158 条
- 击球时间戳疑似错误：79 条
- 语义或字段问题：2 条
- 原标注附近缺少可信击球声音：2 条

## 验证结果

- 数据结构：1,207/1,207 通过
- 音视频可读性与时长一致性：1,207/1,207 通过
- 重剪文件：225/225 通过
- Git 中发生变化的样本目录：220，全部属于批准修改清单
- 未解决样本目录发生变化：0
- 最终时间窗、音频候选、音画偏差、文件哈希和源视频偏移对账错误：0

## 修改明细

| sample | result | before event | after event | before duration | after duration | trajectory |
| --- | --- | --- | --- | ---: | ---: | --- |
| F_0001 | recut_and_retime | 0.940-1.040 | 0.925-1.025 | 7.014 | 12.995 | fly -> fly |
| F_0002 | recut_and_retime | 1.250-1.350 | 1.245-1.345 | 7.014 | 13.315 | fly -> fly |
| F_0004 | recut_and_retime | 3.400-3.500 | 1.955-2.055 | 7.014 | 14.000 | line_drive -> line_drive |
| F_0005 | recut_and_retime | 1.580-1.680 | 1.575-1.675 | 7.014 | 13.635 | fly -> fly |
| F_0006 | recut_and_retime | 0.790-0.890 | 0.785-0.885 | 7.014 | 12.845 | pop_fly -> pop_fly |
| F_0008 | recut_and_retime | 3.400-3.500 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0010 | recut_and_retime | 3.390-3.490 | 1.955-2.055 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0011 | recut_and_retime | 1.060-1.160 | 1.055-1.155 | 7.014 | 13.125 | fly -> fly |
| F_0012 | recut_and_retime | 3.370-3.470 | 1.965-2.065 | 7.015 | 14.000 | line_drive -> line_drive |
| F_0013 | recut_and_retime | 3.300-3.400 | 1.955-2.055 | 7.006 | 14.000 | pop_fly -> pop_fly |
| F_0014 | recut_and_retime | 1.090-1.190 | 1.085-1.185 | 7.014 | 13.155 | fly -> fly |
| F_0016 | recut_and_retime | 3.660-3.760 | 1.955-2.055 | 7.014 | 14.000 | line_drive -> fly |
| F_0018 | recut_and_retime | 1.920-2.020 | 1.905-2.005 | 7.014 | 9.059 | fly -> fly |
| F_0019 | recut_and_retime | 3.980-4.120 | 1.945-2.045 | 7.014 | 14.000 | line_drive -> fly |
| F_0022 | recut_and_retime | 3.440-3.540 | 1.955-2.055 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0025 | recut_and_retime | 0.960-1.060 | 0.945-1.045 | 7.014 | 13.015 | fly -> fly |
| F_0026 | recut_and_retime | 2.300-2.400 | 1.945-2.045 | 7.014 | 14.000 | fly -> fly |
| F_0027 | recut_and_retime | 0.590-0.690 | 0.685-0.785 | 7.014 | 12.755 | line_drive -> line_drive |
| F_0028 | recut_and_retime | 0.910-1.010 | 0.715-0.815 | 7.014 | 12.785 | fly -> fly |
| F_0029 | recut_and_retime | 3.170-3.270 | 1.965-2.065 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0030 | recut_and_retime | 4.670-4.770 | 1.965-2.065 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0032 | recut_and_retime | 3.410-3.510 | 1.945-2.045 | 7.006 | 14.000 | line_drive -> line_drive |
| F_0034 | recut_and_retime | 3.230-3.330 | 1.945-2.045 | 7.014 | 14.000 | fly -> fly |
| F_0035 | recut_and_retime | 3.170-3.270 | 1.935-2.035 | 7.006 | 9.717 | line_drive -> line_drive |
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
| F_0061 | recut_and_retime | 1.180-1.280 | 1.165-1.265 | 7.014 | 13.235 | fly -> fly |
| F_0064 | recut_and_retime | 4.770-4.920 | 1.945-2.045 | 7.012 | 7.350 | line_drive -> line_drive |
| F_0067 | recut_and_retime | 0.570-0.670 | 0.555-0.655 | 7.014 | 12.625 | line_drive -> fly |
| F_0068 | recut_and_retime | 3.600-3.700 | 1.945-2.045 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0069 | recut_and_retime | 4.120-4.220 | 1.955-2.055 | 7.000 | 11.277 | fly -> fly |
| F_0070 | retime_or_metadata_only | 3.110-3.210 | 2.795-2.895 | 7.014 | 7.014 | line_drive -> line_drive |
| F_0071 | recut_and_retime | 1.110-1.210 | 1.965-2.065 | 7.014 | 14.000 | fly -> fly |
| F_0072 | recut_and_retime | 3.480-3.620 | 1.955-2.055 | 7.007 | 10.581 | fly -> fly |
| F_0073 | recut_and_retime | 1.030-1.130 | 1.015-1.115 | 7.014 | 13.085 | fly -> fly |
| F_0075 | recut_and_retime | 1.380-1.480 | 1.955-2.055 | 7.014 | 14.000 | line_drive -> line_drive |
| F_0077 | recut_and_retime | 4.200-4.300 | 1.955-2.055 | 7.007 | 7.094 | line_drive -> line_drive |
| F_0081 | recut_and_retime | 4.310-4.410 | 1.945-2.045 | 7.006 | 14.000 | line_drive -> line_drive |
| F_0082 | recut_and_retime | 4.020-4.120 | 2.445-2.545 | 7.006 | 13.934 | fly -> fly |
| F_0083 | recut_and_retime | 1.640-1.740 | 1.625-1.725 | 7.014 | 13.695 | fly -> fly |
| F_0087 | recut_and_retime | 4.180-4.280 | 1.945-2.045 | 7.014 | 14.000 | fly -> fly |
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
| F_0107 | retime_or_metadata_only | 2.490-2.590 | 2.905-3.005 | 7.014 | 7.014 | line_drive -> line_drive |
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
| F_0129 | recut_and_retime | 0.800-0.950 | 0.505-0.605 | 7.014 | 12.565 | line_drive -> line_drive |
| F_0130 | recut_and_retime | 2.950-3.050 | 1.955-2.055 | 7.014 | 14.000 | fly -> fly |
| F_0131 | recut_and_retime | 1.040-1.150 | 2.385-2.485 | 7.007 | 14.000 | fly -> fly |
| F_0132 | recut_and_retime | 1.950-2.150 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0133 | recut_and_retime | 1.950-2.050 | 1.825-1.925 | 7.014 | 13.895 | fly -> fly |
| F_0134 | recut_and_retime | 0.080-0.180 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0135 | recut_and_retime | 0.270-0.370 | 1.955-2.055 | 7.006 | 10.929 | fly -> fly |
| F_0136 | recut_and_retime | 0.690-0.790 | 1.945-2.045 | 7.000 | 14.000 | fly -> fly |
| F_0138 | recut_and_retime | 1.980-2.080 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0139 | recut_and_retime | 0.400-0.600 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0143 | recut_and_retime | 1.800-2.000 | 1.785-1.885 | 7.014 | 13.845 | fly -> fly |
| F_0144 | recut_and_retime | 0.350-0.550 | 1.575-1.675 | 7.006 | 13.645 | fly -> fly |
| F_0146 | retime_or_metadata_only | 0.100-0.250 | 1.075-1.175 | 7.006 | 7.006 | line_drive -> line_drive |
| F_0147 | recut_and_retime | 0.050-0.150 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0148 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0149 | recut_and_retime | 1.000-1.100 | 0.995-1.095 | 7.014 | 13.065 | fly -> fly |
| F_0150 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0151 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0152 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0153 | recut_and_retime | 0.470-0.570 | 1.955-2.055 | 7.006 | 12.304 | fly -> fly |
| F_0154 | retime_or_metadata_only | 0.450-0.650 | 0.795-0.895 | 7.006 | 7.006 | line_drive -> line_drive |
| F_0155 | recut_and_retime | 0.100-0.250 | 1.955-2.055 | 7.006 | 8.485 | fly -> fly |
| F_0156 | recut_and_retime | 0.300-0.500 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0157 | recut_and_retime | 0.010-0.110 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0158 | recut_and_retime | 0.870-0.970 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0159 | retime_or_metadata_only | 0.800-0.950 | 1.595-1.695 | 7.007 | 7.007 | line_drive -> line_drive |
| F_0160 | recut_and_retime | 0.450-0.550 | 4.265-4.365 | 7.007 | 14.000 | fly -> fly |
| F_0161 | recut_and_retime | 0.430-0.530 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0163 | recut_and_retime | 0.050-0.150 | 0.495-0.595 | 7.014 | 12.565 | fly -> fly |
| F_0165 | recut_and_retime | 0.000-0.150 | 1.955-2.055 | 7.006 | 8.265 | fly -> fly |
| F_0166 | recut_and_retime | 0.800-0.900 | 1.005-1.105 | 7.007 | 10.260 | line_drive -> line_drive |
| F_0167 | recut_and_retime | 1.940-2.040 | 1.955-2.055 | 7.000 | 7.979 | fly -> fly |
| F_0168 | recut_and_retime | 0.170-0.270 | 1.705-1.805 | 7.006 | 13.775 | fly -> fly |
| F_0169 | recut_and_retime | 0.070-0.170 | 3.905-4.005 | 7.006 | 14.000 | fly -> fly |
| F_0171 | recut_and_retime | 0.010-0.110 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0172 | recut_and_retime | 0.000-0.100 | 2.285-2.385 | 7.006 | 14.000 | fly -> fly |
| F_0173 | recut_and_retime | 0.000-0.050 | 1.945-2.045 | 7.006 | 13.062 | fly -> fly |
| F_0174 | recut_and_retime | 0.150-0.250 | 1.955-2.055 | 7.006 | 13.715 | fly -> fly |
| F_0175 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0176 | recut_and_retime | 0.000-0.100 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0177 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.002 | 14.000 | fly -> fly |
| F_0179 | recut_and_retime | 2.800-3.000 | 1.955-2.055 | 7.006 | 6.185 | fly -> fly |
| F_0180 | recut_and_retime | 0.310-0.410 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0181 | recut_and_retime | 1.980-2.080 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0182 | recut_and_retime | 0.270-0.370 | 1.955-2.055 | 7.006 | 9.244 | fly -> fly |
| F_0183 | recut_and_retime | 0.000-0.100 | 1.945-2.045 | 7.007 | 10.623 | fly -> fly |
| F_0184 | recut_and_retime | 1.340-1.440 | 1.345-1.445 | 7.014 | 13.405 | fly -> fly |
| F_0185 | recut_and_retime | 0.230-0.330 | 1.955-2.055 | 7.006 | 7.177 | fly -> fly |
| F_0186 | recut_and_retime | 0.000-0.100 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0187 | recut_and_retime | 1.980-2.080 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0189 | recut_and_retime | 0.000-0.100 | 1.765-1.865 | 7.006 | 10.060 | fly -> fly |
| F_0191 | recut_and_retime | 0.100-0.200 | 1.995-2.095 | 7.006 | 8.445 | fly -> fly |
| F_0193 | recut_and_retime | 1.800-2.000 | 1.035-1.135 | 7.014 | 13.105 | fly -> fly |
| F_0194 | recut_and_retime | 0.660-0.760 | 0.645-0.745 | 7.014 | 12.715 | fly -> fly |
| F_0195 | recut_and_retime | 0.230-0.330 | 1.985-2.085 | 7.007 | 14.000 | fly -> fly |
| F_0196 | recut_and_retime | 5.800-6.000 | 1.945-2.045 | 7.014 | 14.000 | fly -> fly |
| F_0198 | recut_and_retime | 0.050-0.250 | 1.935-2.035 | 7.006 | 14.000 | fly -> fly |
| F_0199 | recut_and_retime | 0.250-0.350 | 1.945-2.045 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0200 | retime_or_metadata_only | 0.430-0.530 | 1.015-1.115 | 7.007 | 7.007 | line_drive -> line_drive |
| F_0201 | recut_and_retime | 0.350-0.550 | 1.935-2.035 | 7.007 | 14.000 | fly -> fly |
| F_0202 | recut_and_retime | 0.570-0.670 | 1.945-2.045 | 7.006 | 14.000 | line_drive -> line_drive |
| F_0205 | recut_and_retime | 0.120-0.280 | 1.955-2.055 | 7.006 | 12.950 | pop_fly -> pop_fly |
| F_0208 | recut_and_retime | 0.250-0.350 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0210 | recut_and_retime | 0.190-0.290 | 1.965-2.065 | 7.006 | 8.745 | line_drive -> line_drive |
| F_0211 | recut_and_retime | 0.330-0.430 | 0.955-1.055 | 7.006 | 13.015 | line_drive -> line_drive |
| F_0212 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.007 | 11.014 | fly -> fly |
| F_0213 | retime_or_metadata_only | 3.090-3.190 | 1.975-2.075 | 7.006 | 7.006 | line_drive -> line_drive |
| F_0217 | recut_and_retime | 0.800-0.900 | 1.355-1.455 | 7.007 | 13.415 | fly -> fly |
| F_0218 | recut_and_retime | 0.110-0.210 | 1.955-2.055 | 7.007 | 12.907 | fly -> fly |
| F_0219 | recut_and_retime | 0.390-0.490 | 1.955-2.055 | 7.006 | 8.585 | fly -> fly |
| F_0221 | recut_and_retime | 1.340-1.440 | 1.325-1.425 | 7.014 | 13.395 | fly -> fly |
| F_0223 | recut_and_retime | 0.450-0.550 | 1.945-2.045 | 7.006 | 12.818 | fly -> fly |
| F_0224 | recut_and_retime | 0.290-0.390 | 1.945-2.045 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0225 | recut_and_retime | 0.800-0.900 | 1.375-1.475 | 7.014 | 13.445 | fly -> fly |
| F_0226 | recut_and_retime | 0.800-0.950 | 0.315-0.415 | 7.014 | 12.385 | fly -> fly |
| F_0227 | recut_and_retime | 0.400-0.600 | 1.905-2.005 | 7.006 | 14.000 | fly -> fly |
| F_0228 | recut_and_retime | 1.080-1.180 | 1.075-1.175 | 7.014 | 13.145 | fly -> fly |
| F_0230 | recut_and_retime | 5.200-5.300 | 1.945-2.045 | 7.006 | 3.735 | fly -> fly |
| F_0231 | recut_and_retime | 0.000-0.150 | 0.365-0.465 | 7.006 | 14.000 | fly -> fly |
| F_0234 | recut_and_retime | 0.250-0.350 | 1.955-2.055 | 7.006 | 12.189 | fly -> fly |
| F_0235 | recut_and_retime | 1.980-2.080 | 1.945-2.045 | 7.007 | 11.347 | fly -> fly |
| F_0236 | recut_and_retime | 1.420-1.520 | 1.955-2.055 | 7.006 | 7.605 | fly -> fly |
| F_0237 | recut_and_retime | 0.800-0.900 | 1.635-1.735 | 7.007 | 11.562 | line_drive -> line_drive |
| F_0238 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0239 | recut_and_retime | 0.630-0.730 | 0.935-1.035 | 7.006 | 13.005 | fly -> fly |
| F_0241 | recut_and_retime | 0.050-0.150 | 0.725-0.825 | 7.007 | 12.785 | fly -> fly |
| F_0242 | recut_and_retime | 1.940-2.040 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0243 | recut_and_retime | 1.060-1.160 | 1.935-2.035 | 7.000 | 7.755 | fly -> fly |
| F_0246 | recut_and_retime | 0.190-0.290 | 1.945-2.045 | 7.007 | 14.000 | line_drive -> line_drive |
| F_0248 | recut_and_retime | 1.960-2.060 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0249 | recut_and_retime | 1.640-1.740 | 1.635-1.735 | 7.014 | 13.695 | fly -> fly |
| F_0250 | recut_and_retime | 1.020-1.120 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0251 | recut_and_retime | 0.980-1.080 | 1.955-2.055 | 7.000 | 7.955 | pop_fly -> pop_fly |
| F_0254 | recut_and_retime | 0.800-1.000 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0255 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.006 | 9.943 | fly -> fly |
| F_0257 | recut_and_retime | 1.780-1.880 | 1.775-1.875 | 7.014 | 13.845 | fly -> fly |
| F_0258 | recut_and_retime | 0.270-0.370 | 1.945-2.045 | 7.006 | 12.199 | fly -> fly |
| F_0260 | recut_and_retime | 1.980-2.080 | 1.955-2.055 | 7.006 | 14.000 | fly -> pop_fly |
| F_0261 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0264 | retime_or_metadata_only | 0.000-0.150 | 1.495-1.595 | 7.007 | 7.007 | line_drive -> line_drive |
| F_0265 | recut_and_retime | 0.000-0.100 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0267 | recut_and_retime | 1.980-2.080 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0268 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 9.058 | fly -> fly |
| F_0269 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0270 | recut_and_retime | 0.270-0.370 | 1.715-1.815 | 7.007 | 13.785 | line_drive -> line_drive |
| F_0271 | recut_and_retime | 0.370-0.470 | 1.935-2.035 | 7.006 | 8.832 | line_drive -> line_drive |
| F_0273 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.006 | 8.785 | fly -> fly |
| F_0275 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.006 | 9.941 | fly -> fly |
| F_0277 | recut_and_retime | 0.510-0.610 | 1.915-2.015 | 7.006 | 9.726 | fly -> fly |
| F_0278 | recut_and_retime | 1.940-2.040 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0279 | recut_and_retime | 0.100-0.300 | 1.945-2.045 | 7.006 | 8.407 | line_drive -> line_drive |
| F_0281 | recut_and_retime | 0.500-0.700 | 1.945-2.045 | 7.007 | 10.665 | line_drive -> line_drive |
| F_0283 | recut_and_retime | 1.960-2.060 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0284 | recut_and_retime | 1.560-1.660 | 1.555-1.655 | 5.488 | 13.615 | fly -> fly |
| F_0285 | recut_and_retime | 1.020-1.120 | 1.015-1.115 | 7.014 | 13.085 | fly -> fly |
| F_0286 | recut_and_retime | 1.320-1.420 | 2.735-2.835 | 7.014 | 13.385 | fly -> fly |
| F_0287 | recut_and_retime | 0.100-0.200 | 1.925-2.025 | 3.086 | 14.000 | fly -> fly |
| F_0288 | recut_and_retime | 1.970-2.070 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0289 | recut_and_retime | 1.430-1.530 | 1.415-1.515 | 7.014 | 13.485 | fly -> fly |
| F_0290 | recut_and_retime | 1.670-1.770 | 1.665-1.765 | 7.014 | 13.735 | fly -> fly |
| F_0291 | recut_and_retime | 1.970-2.070 | 1.945-2.045 | 5.598 | 14.000 | fly -> fly |
| F_0292 | recut_and_retime | 1.970-2.070 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0293 | recut_and_retime | 4.350-4.450 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0294 | recut_and_retime | 1.970-2.070 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0296 | recut_and_retime | 1.970-2.070 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0297 | recut_and_retime | 1.030-1.130 | 1.015-1.115 | 7.014 | 13.085 | fly -> fly |
| F_0298 | recut_and_retime | 1.970-2.070 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0305 | recut_and_retime | 1.950-2.050 | 1.915-2.015 | 7.007 | 13.368 | fly -> fly |
| F_0306 | recut_and_retime | 1.950-2.050 | 1.945-2.045 | 7.006 | 12.492 | fly -> line_drive |
| F_0307 | recut_and_retime | 1.950-2.050 | 1.955-2.055 | 7.007 | 14.000 | fly -> fly |
| F_0308 | recut_and_retime | 1.370-1.470 | 1.375-1.475 | 7.014 | 13.445 | fly -> fly |
| F_0309 | recut_and_retime | 1.950-2.050 | 1.945-2.045 | 7.007 | 14.000 | fly -> fly |
| F_0310 | recut_and_retime | 1.950-2.050 | 1.955-2.055 | 7.006 | 13.064 | fly -> fly |
| F_0312 | recut_and_retime | 1.950-2.050 | 0.675-0.775 | 7.007 | 14.000 | fly -> fly |
| F_0315 | recut_and_retime | 1.950-2.050 | 1.945-2.045 | 7.006 | 14.000 | fly -> fly |
| F_0316 | recut_and_retime | 1.950-2.050 | 1.955-2.055 | 7.006 | 14.000 | fly -> fly |
| F_0318 | recut_and_retime | 0.610-0.710 | 0.615-0.715 | 7.014 | 12.675 | fly -> fly |
| F_0319 | recut_and_retime | 3.050-3.150 | 1.945-2.045 | 7.006 | 5.975 | line_drive -> line_drive |
| F_0325 | recut_and_retime | 1.950-2.050 | 1.955-2.055 | 7.006 | 7.626 | fly -> fly |
| F_0328 | retime_or_metadata_only | 2.990-3.090 | 1.175-1.275 | 7.006 | 7.006 | line_drive -> line_drive |

## 保持原样的未解决样本

| 样本 | 原始首要错误 | 未写回原因 |
| --- | --- | --- |
| F_0085 | clip_too_short | no_candidate_selected |
| F_0115 | clip_too_short | no_candidate_selected |
| F_0125 | clip_too_short | no_candidate_selected |
| F_0229 | clip_too_short | no_candidate_selected |
| F_0232 | contact_timestamp_wrong | no_candidate_selected |
| F_0244 | clip_too_short | no_candidate_selected |
| F_0252 | clip_too_short | no_candidate_selected |
| F_0295 | clip_too_short | no_candidate_selected |
| F_0299 | clip_too_short | no_candidate_selected |
| F_0300 | clip_too_short | no_candidate_selected |
| F_0301 | clip_too_short | no_candidate_selected |
| F_0303 | clip_too_short | no_candidate_selected |
| F_0313 | clip_too_short | no_candidate_selected |
| F_0314 | clip_too_short | no_candidate_selected |
| F_0320 | contact_timestamp_wrong | no_candidate_selected |
| F_0322 | contact_timestamp_wrong | no_candidate_selected |
| F_0323 | contact_timestamp_wrong | no_candidate_selected |
| F_0324 | source_recovery_required | no_candidate_selected |
| F_0326 | contact_timestamp_wrong | no_candidate_selected |
| F_0330 | contact_timestamp_wrong | no_candidate_selected |
| F_0331 | contact_timestamp_wrong | audio_visual_time_mismatch |
