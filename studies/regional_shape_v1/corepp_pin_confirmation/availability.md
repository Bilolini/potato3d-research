# Fresh-potato availability for CoRe++

The metadata inventory found **233 eligible potatoes fresh to our experiments**, including **29 on the model-test split**. The 29 span five acquisition groups and three cultivars. All 29 were selected. Their experiment scope is one registered RGB-D frame per potato from this release. The selection uses no model output or reference geometry. [Frozen roster](roster.json) · [Full inventory](inventory.json)

The full-data assignments come from the published CoRe++ split generator applied to all 339 dataset labels. Its 237 train, 51 validation, and 51 test objects match the counts in the model paper. The authors' five-object demo split differs from the full-data rules, and its potatoes were excluded. The checkpoint bundle provides no separate object-level training ledger, so the model-test status is based on the released split rules. The `exp_split` field in the 3DPotatoTwin traits file is retained separately. Among the 29 selected objects it labels 21 train, seven exclude, and one test. [Full split generator](https://github.com/UTokyo-FieldPhenomics-Lab/corepp/blob/0d6bae40b9215332efd566e6bca83bea171b99e9/data_preparation/make_splits.py) · [CoRe++ paper, §2.1.4](https://www.ipb.uni-bonn.de/wp-content/papercite-data/pdf/blok2025cea.pdf#page=4) · [Trait metadata](https://huggingface.co/datasets/UTokyo-FieldPhenomics-Lab/3DPotatoTwin/blob/main/3_pair/ground_truth.csv)

The 89 previous objects comprise five demo, twelve development, and 72 from the two closed cohorts. Seventeen additional objects were excluded for registration warnings, including the normalized spelling `2R3-6` for `2R306`. All remaining candidates had a registration JSON pointing to an RGB-D frame with both ZIP members and one released pin polygon. Only the ZIP metadata and JSON and CSV release records were consulted. [Eligibility protocol](../corepp_pin_confirmation_protocol.md)

## Eligible by cultivar

| Cultivar | Model train | Model validation | Model test | Selected |
| --- | ---: | ---: | ---: | ---: |
| Corolle | 0 | 0 | 1 | 1 |
| Kitahime | 9 | 8 | 7 | 7 |
| Sayaka | 164 | 23 | 21 | 21 |

## Eligible by acquisition group

The acquisition group is the release's `ros_bag_name`. Release total includes all listed potatoes in the group, including prior exclusions.

| Cultivar | Acquisition group | Release total | Model train | Model validation | Model test | Selected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Corolle | `20230922_barn_okadasan_sarabetsu_01` | 10 | 0 | 0 | 0 | 0 |
| Corolle | `20230922_barn_okadasan_sarabetsu_02` | 10 | 0 | 0 | 1 | 1 |
| Corolle | `20230922_barn_okadasan_sarabetsu_03` | 10 | 0 | 0 | 0 | 0 |
| Kitahime | `20230915_barn_okadasan_sarabetsu_01` | 11 | 9 | 0 | 0 | 0 |
| Kitahime | `20230915_barn_okadasan_sarabetsu_02` | 10 | 0 | 8 | 0 | 0 |
| Kitahime | `20230915_barn_okadasan_sarabetsu_03` | 10 | 0 | 0 | 7 | 7 |
| Sayaka | `20230914_field_okadasan_sarabetsu_02` | 40 | 23 | 9 | 0 | 0 |
| Sayaka | `20230914_field_okadasan_sarabetsu_03` | 50 | 43 | 0 | 0 | 0 |
| Sayaka | `20230914_field_okadasan_sarabetsu_04` | 20 | 14 | 0 | 0 | 0 |
| Sayaka | `20230914_field_okadasan_sarabetsu_05` | 20 | 4 | 0 | 10 | 10 |
| Sayaka | `20230921_field_okadasan_sarabetsu_03` | 28 | 9 | 8 | 5 | 5 |
| Sayaka | `20230921_field_okadasan_sarabetsu_04` | 20 | 12 | 0 | 0 | 0 |
| Sayaka | `20230921_field_okadasan_sarabetsu_05` | 10 | 6 | 0 | 0 | 0 |
| Sayaka | `20230921_field_okadasan_sarabetsu_06` | 10 | 5 | 0 | 0 | 0 |
| Sayaka | `20230921_field_okadasan_sarabetsu_08` | 20 | 16 | 0 | 0 | 0 |
| Sayaka | `20230921_field_okadasan_sarabetsu_09` | 20 | 8 | 6 | 0 | 0 |
| Sayaka | `20230921_field_okadasan_sarabetsu_10` | 20 | 16 | 0 | 0 | 0 |
| Sayaka | `20230921_field_okadasan_sarabetsu_11` | 20 | 8 | 0 | 6 | 6 |

The roster SHA-256 is `502cd15bf479be089dd616216dc5933a61a75f4ddc7d96bc6fb45668e97e8525`. The frozen protocol SHA-256 is `56013355bdde2260885d9f71362dd677d4f016674d4636596f1ebf565db97390`.
