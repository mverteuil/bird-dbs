# Ground Truth: Manual Calculation for 10-Record Test

## Test Records Summary

| ID | Species | Checklist | Lat | Lon | Date | Complete | Group |
|----|---------|-----------|-----|-----|------|----------|-------|
| OBS001 | Robin | S001 | 40.0 | -75.0 | 2024-01-01 | ✓ | (empty) |
| OBS002 | Robin | S001 | 40.0 | -75.0 | 2024-01-01 | ✓ | G001 |
| OBS003 | Cardinal | S001 | 40.0 | -75.0 | 2024-01-01 | ✓ | G001 |
| OBS004 | Robin | S002 | 40.0 | -75.0 | 2024-01-02 | ✓ | G002 |
| OBS005 | Robin | S003 | 40.1 | -75.1 | 2024-01-02 | ✓ | (empty) |
| OBS006 | Robin | S003 | 40.1 | -75.1 | 2024-01-02 | ✓ | (empty) |
| OBS007 | Robin | S004 | 40.0 | -75.0 | 2024-02-01 | ✗ | G003 |
| OBS008 | Sparrow | S005 | 40.0 | -75.0 | 2024-02-01 | ✓ | G004 |
| OBS009 | Robin | S006 | 41.0 | -75.0 | 2024-01-01 | ✓ | G005 |
| OBS010 | Robin | S006 | 41.0 | -75.0 | 2024-01-01 | ✓ | G005 |

## Edge Cases Tested

1. **Same checklist, multiple observations**: S001 has 3 obs (OBS001, OBS002, OBS003)
2. **Mixed GROUP_IDENTIFIER**: S001 spans records with and without GROUP_ID
3. **Duplicate observations**: S003 (OBS005, OBS006) and S006 (OBS009, OBS010)
4. **Incomplete checklist**: S004 (OBS007) should NOT count in frequency
5. **Multiple cells**: Coordinates span 3 different H3 cells
6. **Multiple species**: Robin, Cardinal, Sparrow
7. **Temporal variation**: January and February observations

## Expected Results

### Cell at H3(40.0, -75.0) at resolution 8

**Total complete checklists in cell**: 3 (S001, S002, S005)

**avibase-TEST0001 (American Robin)**:
- Total observations: 3 (OBS001, OBS002, OBS004)
- Complete checklists: 2 (S001, S002)
- Incomplete observations: 1 (OBS007 from S004)
- Yearly frequency: 2/3 = 0.6667
- Monthly checklists: [2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] (Jan=2, Feb=0 because S004 incomplete)
- Monthly observations: [3, 1, 0, ...] (Jan=3, Feb=1)
- First observation: 2024-01-01
- Last observation: 2024-02-01

**avibase-TEST0002 (Northern Cardinal)**:
- Total observations: 1 (OBS003)
- Complete checklists: 1 (S001)
- Yearly frequency: 1/3 = 0.3333
- Monthly checklists: [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
- Monthly observations: [1, 0, 0, ...]

**avibase-TEST0003 (House Sparrow)**:
- Total observations: 1 (OBS008)
- Complete checklists: 1 (S005)
- Yearly frequency: 1/3 = 0.3333
- Monthly checklists: [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
- Monthly observations: [0, 1, 0, ...]

### Cell at H3(40.1, -75.1) at resolution 8

**Total complete checklists in cell**: 1 (S003)

**avibase-TEST0001 (American Robin)**:
- Total observations: 2 (OBS005, OBS006)
- Complete checklists: 1 (S003)
- Yearly frequency: 1/1 = 1.0
- Monthly checklists: [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
- Monthly observations: [0, 2, 0, ...]

### Cell at H3(41.0, -75.0) at resolution 8

**Total complete checklists in cell**: 1 (S006)

**avibase-TEST0001 (American Robin)**:
- Total observations: 2 (OBS009, OBS010)
- Complete checklists: 1 (S006)
- Yearly frequency: 1/1 = 1.0
- Monthly checklists: [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
- Monthly observations: [1, 0, 0, ...]

## Validation Rules

Any implementation that produces different numbers is **INCORRECT**.

Specifically:
- ✓ S001 must count as ONE checklist (not 3) despite having 3 observations
- ✓ S004 must NOT count in frequency calculations (incomplete)
- ✓ Same checklist in different cells must count separately per cell
- ✓ Temporal aggregations must reflect the actual dates
- ✓ Total checklists per species per cell ≤ total complete checklists in that cell
