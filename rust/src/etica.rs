use calamine::{open_workbook_auto, DataType, Reader};
use chrono::NaiveDate;
use linreg::linear_regression_of;
use polars::prelude::*;
use std::fs;
use std::path::{Path, PathBuf};
use tracing::{error, info, warn};

pub const COL_DATA: &str = "Data contabile";
pub const COL_SALDO: &str = "Saldo";
pub const COL_PLUS: &str = "Avere";
pub const COL_MINUS: &str = "Dare";
pub const COL_DESCR: &str = "Descrizione";
pub const COL_INV: &str = "Blacklisted";
pub const COL_RUN_TOT: &str = "Running Total";
pub const COL_OLS: &str = "OLS";

pub fn data_dir() -> PathBuf {
    PathBuf::from("data/etica")
}

/// Converts any .xls/.xlsx files in the directory to .csv
pub fn convert_excel_to_csv() -> color_eyre::Result<()> {
    let dir = data_dir();
    if !dir.exists() {
        warn!("Data directory {:?} does not exist.", dir);
        return Ok(());
    }

    for entry in fs::read_dir(dir)?.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("xls") {
            info!("Converting Excel file to CSV: {:?}", path);
            let mut workbook = open_workbook_auto(&path)?;
            let sheet_name = workbook.sheet_names()[0].clone();
            if let Ok(range) = workbook.worksheet_range(&sheet_name) {
                let csv_path = path.with_extension("csv");
                let mut wtr = csv::Writer::from_path(&csv_path)?;
                for row in range.rows() {
                    let record: Vec<String> = row.iter().map(|c| match c {
                        DataType::String(s) => s.to_string(),
                        DataType::Float(f) => f.to_string(),
                        DataType::Int(i) => i.to_string(),
                        DataType::DateTime(d) => d.to_string(),
                        _ => String::new(),
                    }).collect();
                    wtr.write_record(&record)?;
                }
                wtr.flush()?;
                fs::remove_file(&path)?;
                info!("Converted and removed {:?}", path);
            }
        }
    }
    Ok(())
}

/// Core pipeline: loads CSVs, merges, deduplicates, and computes running totals
pub fn load_data() -> color_eyre::Result<DataFrame> {
    info!("Starting data load pipeline...");
    convert_excel_to_csv()?;

    let mut lf_vec = Vec::new();
    let dir = data_dir();
    
    // Load all CSVs except merged and blacklist
    for entry in fs::read_dir(&dir)?.flatten() {
        let path = entry.path();
        let name = path.file_name().unwrap_or_default().to_string_lossy();
        if path.extension().and_then(|e| e.to_str()) == Some("csv") 
            && name != "merged.csv" && name != "blacklist.csv" {
            
            let lf = LazyCsvReader::new(&path)
                .with_has_header(true)
                .with_ignore_errors(true)
                .finish()?;
            lf_vec.push(lf);
        }
    }

    if lf_vec.is_empty() {
        return Ok(DataFrame::empty());
    }

    // Concatenate and Deduplicate
    let mut df = concat(lf_vec, UnionArgs::default())?.unique(None, UniqueKeepStrategy::First).collect()?;
    
    // Sort by Date
    df = df.sort([COL_DATA], vec![false], false)?;

    // Handle 'Importo' & 'Running Total' using Polars Expressions
    let lf = df.lazy()
        .with_column(
            (col(COL_PLUS).fill_null(lit(0.0)) + col(COL_MINUS).fill_null(lit(0.0)))
            .alias("Importo")
        )
        .with_column(
            col("Importo").cum_sum(false).alias(COL_RUN_TOT)
        );

    df = lf.collect()?;
    info!("Pipeline completed. Loaded {} rows.", df.height());

    Ok(df)
}

/// Compute OLS (Ordinary Least Squares) linear regression: y = mx + q
pub fn compute_ols(df: &DataFrame) -> color_eyre::Result<(f64, f64)> {
    let dates = df.column(COL_DATA)?.str()?;
    let saldos = df.column(COL_RUN_TOT)?.f64()?;

    let mut x_vals = Vec::new();
    let mut y_vals = Vec::new();

    for (i, d) in dates.into_iter().enumerate() {
        if let (Some(date_str), Some(saldo)) = (d, saldos.get(i)) {
            if let Ok(nd) = NaiveDate::parse_from_str(date_str, "%Y-%m-%d") {
                // Use ordinal days for X axis math
                x_vals.push(nd.num_days_from_ce() as f64);
                y_vals.push(saldo);
            }
        }
    }

    if x_vals.len() < 2 {
        warn!("Not enough data for OLS fit.");
        return Ok((0.0, 0.0));
    }

    // Compute Linear Regression
    match linear_regression_of(&x_vals, &y_vals) {
        Ok((slope, intercept)) => Ok((slope, intercept)),
        Err(e) => {
            error!("OLS Fit failed: {}", e);
            Ok((0.0, 0.0))
        }
    }
}
