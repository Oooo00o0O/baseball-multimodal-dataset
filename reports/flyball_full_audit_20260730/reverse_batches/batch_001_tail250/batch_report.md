# Flyball Reverse Batch 001 Audit Report

## Scope

- Queue rows: 250
- Audit order: global index 1207 down to 958
- Decision standard: visible batting/contact action plus matching normal-speed bat-contact audio.
- Trailing catch/play replay is allowed; selected slow-motion or commentary audio is not.

## Outcomes

- metadata_time_correction: 71
- needs_source_recut: 179

## Recut Categories

- candidate_rejected_by_independent_review: 1
- contact_pair_unverified: 21
- independent_multimodal_confirmation: 71
- no_verified_live_contact_in_clip: 110
- visible_contact_audio_unresolved: 47

## Applied Metadata Corrections

| Sample | Before | After | Independent reviewer |
|---|---:|---:|---|
| dataset/fly_ball/Zhengxuan_Liu/F_033 | 1.138 to 1.15 | 1.095 to 1.195 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_031 | 2.171 to 2.179 | 2.123 to 2.223 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_030 | 1.115 to 1.122 | 1.065 to 1.165 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_029 | 1.204 to 1.211 | 1.155 to 1.255 | qwen-omni-turbo |
| dataset/fly_ball/Zhengxuan_Liu/F_028 | 0.852 to 0.859 | 0.806 to 0.906 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_027 | 1.148 to 1.156 | 1.100 to 1.200 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_026 | 1.297 to 1.307 | 1.250 to 1.350 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_023 | 0.443 to 0.451 | 0.396 to 0.496 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_022 | 2.035 to 2.047 | 1.988 to 2.088 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_020 | 1.127 to 1.132 | 1.080 to 1.180 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_019 | 0.866 to 0.874 | 0.821 to 0.921 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_018 | 0.998 to 1.008 | 0.950 to 1.050 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_017 | 0.788 to 0.796 | 0.741 to 0.841 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_016 | 0.838 to 0.847 | 0.791 to 0.891 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_015 | 0.603 to 0.62 | 0.561 to 0.661 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_014 | 1.893 to 1.903 | 1.848 to 1.948 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_013 | 2.134 to 2.142 | 2.088 to 2.188 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_012 | 1.301 to 1.312 | 1.255 to 1.355 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_011 | 0.816 to 0.826 | 0.771 to 0.871 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_009 | 0.823 to 0.833 | 0.776 to 0.876 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_007 | 0.642 to 0.656 | 0.596 to 0.696 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_006 | 1.207 to 1.22 | 0.641 to 0.741 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_005 | 1.947 to 1.951 | 1.898 to 1.998 | qwen3.5-omni-flash |
| dataset/fly_ball/Zhengxuan_Liu/F_001 | 1.508 to 1.517 | 1.459 to 1.559 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1288 | 1.950 to 2.050 | 0.912 to 1.012 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1283 | 1.950 to 2.050 | 1.957 to 2.057 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1278 | 1.830 to 1.930 | 1.848 to 1.948 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1276 | 0.230 to 0.330 | 2.618 to 2.718 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1275 | 1.950 to 2.050 | 0.847 to 0.947 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1270 | 1.950 to 2.050 | 1.977 to 2.077 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1250 | 1.950 to 2.050 | 0.813 to 0.913 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1246 | 1.790 to 1.890 | 1.822 to 1.922 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1231 | 0.990 to 1.090 | 1.022 to 1.122 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1230 | 0.970 to 1.070 | 1.008 to 1.108 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1226 | 1.950 to 2.050 | 0.327 to 0.427 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1222 | 1.150 to 1.250 | 1.177 to 1.277 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1221 | 1.210 to 1.310 | 1.238 to 1.338 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1217 | 1.950 to 2.050 | 0.077 to 0.177 | qwen3.5-omni-flash |
| dataset/fly_ball/Codex_Workstation/F_1216 | 1.950 to 2.050 | 1.973 to 2.073 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1213 | 2.973 to 3.073 | 1.863 to 1.963 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1212 | 1.690 to 1.790 | 1.718 to 1.818 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1207 | 1.750 to 1.850 | 1.782 to 1.882 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1206 | 1.950 to 2.050 | 1.973 to 2.073 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1205 | 1.950 to 2.050 | 1.973 to 2.073 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1204 | 1.070 to 1.170 | 1.088 to 1.188 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1198 | 1.130 to 1.230 | 1.152 to 1.252 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1197 | 3.877 to 3.977 | 0.678 to 0.778 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1196 | 1.710 to 1.810 | 1.748 to 1.848 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1190 | 1.950 to 2.050 | 1.967 to 2.067 | qwen-omni-turbo |
| dataset/fly_ball/Codex_Workstation/F_1184 | 1.950 to 2.050 | 1.977 to 2.077 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1178 | 1.950 to 2.050 | 0.037 to 0.137 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1172 | 0.750 to 0.850 | 0.777 to 0.877 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1169 | 1.950 to 2.050 | 1.973 to 2.073 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1162 | 1.010 to 1.110 | 1.027 to 1.127 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1158 | 1.650 to 1.750 | 1.672 to 1.772 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1157 | 1.950 to 2.050 | 1.138 to 1.238 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1156 | 1.810 to 1.910 | 1.828 to 1.928 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1153 | 2.954 to 3.054 | 0.148 to 0.248 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1146 | 1.310 to 1.410 | 1.333 to 1.433 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1144 | 1.950 to 2.050 | 5.212 to 5.312 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1141 | 1.950 to 2.050 | 1.008 to 1.108 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1136 | 1.530 to 1.630 | 1.537 to 1.637 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1135 | 1.790 to 1.890 | 1.797 to 1.897 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1134 | 1.870 to 1.970 | 1.883 to 1.983 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1132 | 1.970 to 2.070 | 1.987 to 2.087 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1129 | 1.610 to 1.710 | 1.623 to 1.723 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1128 | 5.850 to 5.950 | 1.243 to 1.343 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1125 | 1.970 to 2.070 | 1.977 to 2.077 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1110 | 1.950 to 2.050 | 1.172 to 1.272 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1108 | 1.950 to 2.050 | 1.172 to 1.272 | qwen3.5-omni-plus |
| dataset/fly_ball/Codex_Workstation/F_1065 | 1.950 to 2.050 | 0.000 to 0.073 | qwen3.5-omni-plus |

## Pending Source Recovery

- 179 rows remain unchanged in the dataset and are listed in the recut CSV.
- They are not cleared, deleted, or published as corrected training samples.
