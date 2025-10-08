use anyhow::Result;
use h3o::{CellIndex, LatLng, Resolution};

pub struct H3Grid {
    resolution: Resolution,
}

impl H3Grid {
    pub fn new(resolution: u8) -> Result<Self> {
        let resolution = Resolution::try_from(resolution)?;
        Ok(Self { resolution })
    }

    pub fn lat_lon_to_cell(&self, lat: f64, lon: f64) -> Result<CellIndex> {
        let coord = LatLng::new(lat, lon)?;
        Ok(coord.to_cell(self.resolution))
    }

    pub fn cell_to_lat_lon(&self, cell: CellIndex) -> (f64, f64) {
        let coord: LatLng = cell.into();
        (coord.lat(), coord.lng())
    }

    pub fn cell_to_i64(&self, cell: CellIndex) -> i64 {
        // Convert H3 CellIndex to 64-bit integer for SQLite storage
        u64::from(cell) as i64
    }

    #[allow(dead_code)]
    pub fn i64_to_cell(&self, value: i64) -> Result<CellIndex> {
        Ok(CellIndex::try_from(value as u64)?)
    }

    pub fn resolution(&self) -> u8 {
        self.resolution as u8
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_h3_grid_creation() {
        let grid = H3Grid::new(7).unwrap();
        assert_eq!(grid.resolution(), 7);
    }

    #[test]
    fn test_lat_lon_to_cell() {
        let grid = H3Grid::new(7).unwrap();
        // San Francisco Mission District
        let cell = grid.lat_lon_to_cell(37.7599, -122.4194).unwrap();
        let cell_i64 = grid.cell_to_i64(cell);

        // Should be a valid cell
        assert!(cell_i64 != 0);
    }

    #[test]
    fn test_cell_roundtrip() {
        let grid = H3Grid::new(7).unwrap();
        let lat = 37.7599;
        let lon = -122.4194;

        let cell = grid.lat_lon_to_cell(lat, lon).unwrap();
        let (lat2, lon2) = grid.cell_to_lat_lon(cell);

        // Should be close (within H3 cell precision)
        assert!((lat - lat2).abs() < 0.01);
        assert!((lon - lon2).abs() < 0.01);
    }
}
